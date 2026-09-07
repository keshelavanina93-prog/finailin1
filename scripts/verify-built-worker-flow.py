"""Execute authentic retained workflows through an isolated built API and owned worker."""

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("built_runtime", ROOT / "scripts/verify-built-runtime.py")
runtime = importlib.util.module_from_spec(loader)
loader.loader.exec_module(runtime)
worker_loader = importlib.util.spec_from_file_location("built_worker", ROOT / "scripts/prepare-built-worker.py")
worker_tools = importlib.util.module_from_spec(worker_loader)
worker_loader.loader.exec_module(worker_tools)


def verify(receipt_path, python, name, queue, resume_from=None):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
        raise ValueError("Invalid candidate name")
    if not re.fullmatch(r"g8-candidate-[a-z0-9][a-z0-9-]{0,79}", queue):
        raise ValueError("A distinct candidate queue is required")
    if (ROOT / ".finai/built-workers" / f"{name}.json").exists():
        raise ValueError("Choose a fresh candidate name; existing worker ownership is preserved")
    paths = runtime.source_tools
    for path in (receipt_path, python):
        paths.check_path(path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    wheel = Path(receipt["wheel"])
    paths.check_path(wheel)
    if paths.file_digest(wheel) != receipt["wheel_sha256"]:
        raise ValueError("Candidate wheel hash mismatch")
    previous = None
    if resume_from is not None:
        paths.check_path(resume_from)
        previous = json.loads((resume_from / "verification.json").read_text(encoding="utf-8"))
        if (previous["status"] != "FAILED" or previous["wheel_sha256"] != receipt["wheel_sha256"]
                or previous["task_queue"] != queue):
            raise ValueError("Recovery requires failed evidence for this exact artifact and queue")
        for filename in ("first-workflow.json", "second-workflow.json"):
            paths.check_path(resume_from / filename)
            retained = json.loads((resume_from / filename).read_text(encoding="utf-8"))
            if not retained.get("request", {}).get("request_id"):
                raise ValueError("Recovery requires the original retained workflow requests")
    parent = ROOT / ".finai/runtime-proof"
    paths.check_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="built-worker-flow-", dir=parent))
    interpreter = worker_tools.verify_interpreter(python, stage)
    installed = runtime.verify_installed(python, wheel, stage)
    runtime.available(8063)
    for child in ("cache", "tmp"):
        (stage / child).mkdir()
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update(FINAI_TEMPORAL_TASK_QUEUE=queue, PYTHONDONTWRITEBYTECODE="1",
                       TEMP=str(stage / "tmp"), TMP=str(stage / "tmp"),
                       XDG_CACHE_HOME=str(stage / "cache"))
    powershell = shutil.which("pwsh")
    if powershell is None:
        raise ValueError("PowerShell supervisor runtime unavailable")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    index = 0

    def run(command):
        nonlocal index
        index += 1
        with (stage / f"step-{index}.log").open("wb") as output:
            result = subprocess.run(command, cwd=stage, env=environment,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, timeout=240, creationflags=flags, check=False)
        if result.returncode:
            raise ValueError(f"Packaged worker verification step {index} failed; retained log available")

    def worker(action):
        run([powershell, "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "scripts/g8-built-worker.ps1"), "-Action", action, "-Name", name,
             "-ApiReceipt", str(receipt_path), "-Python", str(python), "-Queue", queue])

    def proof(destination, mode=None):
        command = [str(python), "-B", "-I", "-X", "pycache_prefix=" + str(stage / "cache"),
                   str(ROOT / "scripts/verify-packaged-worker-runtime.py"),
                   "--base-url", "http://127.0.0.1:8063/v1/ontology", "--output", str(destination)]
        run(command + ([mode] if mode else []))

    def launch_record():
        state = json.loads((ROOT / ".finai/built-workers" / f"{name}.json").read_text(encoding="utf-8-sig"))
        path = Path(state["launch_receipt"])
        paths.check_path(path)
        if paths.file_digest(path) != state["launch_receipt_sha256"]:
            raise ValueError("Worker launch evidence changed")
        return {"state": state, "launch": json.loads(path.read_text(encoding="utf-8"))}

    def stop_api(process):
        if os.name == "nt" and process.poll() is None:
            # The still-open Popen process handle identifies this launch. Windows
            # venv launchers can own a base-interpreter child running the API.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=15, check=True, creationflags=flags)
        runtime.stop_owned(process)

    result = {"contract": "g8-built-worker-flow/1", "wheel_sha256": receipt["wheel_sha256"],
              "commit": receipt["commit"], "source_archive_sha256": receipt["archive_sha256"],
              "installed_api_package": installed, "python": str(python),
              "interpreter": interpreter,
              "python_sha256": paths.file_digest(python), "task_queue": queue,
              "proof_directory": str(stage), "release_accepted": False,
              "verification_script_sha256": paths.file_digest(Path(__file__))}
    if previous is not None:
        result["recovery_from"] = {"directory": str(resume_from),
                                   "verification_sha256": paths.file_digest(resume_from / "verification.json"),
                                   "prior_error": previous["error"]}
        for filename in ("first-workflow.json", "second-workflow.json"):
            shutil.copyfile(resume_from / filename, stage / filename)
    api = None
    worker_started = False
    failure = None
    try:
        with (stage / "api.log").open("wb") as log:
            api = subprocess.Popen([str(python), "-B", "-I", "-X",
                                    "pycache_prefix=" + str(stage / "cache"), "-m", "uvicorn",
                                    "finai_api.main:app", "--host", "127.0.0.1", "--port", "8063",
                                    "--no-access-log", "--log-level", "error"],
                                   cwd=stage, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
            with httpx.Client(timeout=10, trust_env=False) as client:
                runtime.wait_ready(client, "http://127.0.0.1:8063/ready", api)
            worker_started = True
            worker("start")
            first_launch = launch_record()
            if previous is None:
                proof(stage / "first-workflow.json", "--prepare")
                proof(stage / "first-workflow.json")
                completed = stage / "first-workflow.json"
                new_work = stage / "second-workflow.json"
            else:
                proof(stage / "first-workflow.json", "--replay")
                proof(stage / "second-workflow.json", "--replay")
                completed = stage / "second-workflow.json"
                new_work = stage / "third-workflow.json"
            worker("stop")
            worker_started = False
            worker_started = True
            worker("start")
            second_launch = launch_record()
            if first_launch["state"]["created"] == second_launch["state"]["created"]:
                raise ValueError("Worker did not restart")
            proof(completed, "--replay")
            proof(new_work)
            result.update(status="LOCAL_PACKAGED_WORKFLOW_PASS", worker_launches=[first_launch, second_launch],
                          first_workflow=json.loads((stage / "first-workflow.json").read_text(encoding="utf-8")),
                          second_workflow=json.loads((stage / "second-workflow.json").read_text(encoding="utf-8")),
                          completed_history_replayed_after_worker_restart=True,
                          new_work_executed_after_worker_restart=True,
                          prior_request_resumed=previous is not None,
                          interrupted_work_recovery_proven=False)
            if previous is not None:
                result["third_workflow"] = json.loads(new_work.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, httpx.HTTPError) as exc:
        result.update(status="FAILED", error=str(exc))
        failure = exc
    finally:
        try:
            try:
                if worker_started:
                    worker("stop")
            finally:
                if api is not None:
                    stop_api(api)
            result["owned_processes_stopped"] = True
            # A closed listener can leave Windows TCP TIME_WAIT entries that
            # prevent immediate exclusive rebinding. That is not a live process.
            deadline = time.monotonic() + 10
            while True:
                with socket.socket() as probe:
                    probe.settimeout(1)
                    listening = probe.connect_ex(("127.0.0.1", 8063)) == 0
                if not listening or time.monotonic() >= deadline:
                    break
                time.sleep(0.25)
            result["candidate_api_port_closed"] = not listening
            if listening:
                raise ValueError("Candidate API port still accepts connections after owned shutdown")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            result.update(status="FAILED", cleanup_error=str(exc))
            if failure is None:
                failure = exc
        finally:
            (stage / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failure is not None:
        raise ValueError(f"Packaged workflow verification failed; evidence: {stage / 'verification.json'}") from failure
    return {"verification": str(stage / "verification.json"), "status": result["status"],
            "owned_processes_stopped": result["owned_processes_stopped"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-receipt", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--name", default="packaged-validation")
    parser.add_argument("--queue", default="g8-candidate-packaged-validation")
    parser.add_argument("--resume-from", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.api_receipt.absolute(), arguments.python.absolute(),
                            arguments.name, arguments.queue,
                            arguments.resume_from.absolute() if arguments.resume_from else None), indent=2))
