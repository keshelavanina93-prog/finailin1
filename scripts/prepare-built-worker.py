"""Verify an installed API artifact and retain a candidate-worker launch specification."""

import argparse
import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "g8_built_runtime", ROOT / "scripts/verify-built-runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
paths = runtime.source_tools


def verify_interpreter(python, stage):
    """A D-resident venv launcher alone does not prove a D-resident interpreter."""
    configuration = python.parent.parent / "pyvenv.cfg"
    if configuration.is_file():
        paths.check_path(configuration)
        entries = dict(
            line.split("=", 1)
            for line in configuration.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        home = next(
            (value.strip() for key, value in entries.items() if key.strip() == "home"),
            None,
        )
        if home is None:
            raise ValueError("Virtual environment base interpreter is not declared")
        paths.check_path(Path(home))
    probe = subprocess.run(
        [
            str(python),
            "-B",
            "-I",
            "-X",
            "pycache_prefix=" + str(stage / "probe-cache"),
            "-c",
            "import json,sys,sysconfig; print(json.dumps({'base_prefix':sys.base_prefix,'stdlib':sysconfig.get_path('stdlib')}))",
        ],
        cwd=stage,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    observed = json.loads(probe.stdout)
    for value in observed.values():
        paths.check_path(Path(value))
    return observed


def prepare(receipt_path, python, queue, parent):
    if re.fullmatch(r"g8-candidate-[a-z0-9][a-z0-9-]{0,79}", queue) is None:
        raise ValueError("A distinct candidate queue is required")
    for path in (receipt_path, python, parent):
        paths.check_path(path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    wheel = Path(receipt["wheel"])
    paths.check_path(wheel)
    if paths.file_digest(wheel) != receipt["wheel_sha256"]:
        raise ValueError("Selected API wheel failed integrity verification")
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="worker-", dir=parent))
    interpreter = verify_interpreter(python, stage)
    installed = runtime.verify_installed(python, wheel, stage)
    for name in ("cache", "tmp"):
        (stage / name).mkdir()
    result = {
        "contract": "g8-built-worker-launch/1",
        "wheel": str(wheel),
        "wheel_sha256": receipt["wheel_sha256"],
        "api_source_commit": receipt["commit"],
        "api_source_archive_sha256": receipt["archive_sha256"],
        "api_build_receipt": str(receipt_path),
        "api_build_receipt_sha256": paths.file_digest(receipt_path),
        "python": str(python),
        "python_sha256": paths.file_digest(python),
        "interpreter": interpreter,
        "installed_api_package": installed,
        "cwd": str(stage),
        "task_queue": queue,
        "prepare_script_sha256": paths.file_digest(Path(__file__)),
        "verifier_script_sha256": paths.file_digest(
            ROOT / "scripts/verify-built-runtime.py"
        ),
        "supervisor_script_sha256": paths.file_digest(
            ROOT / "scripts/g8-built-worker.ps1"
        ),
        "observation": "VERIFIED_PACKAGE_BYTES_ONLY",
        "execution_proven": False,
        "release_accepted": False,
    }
    destination = stage / "launch.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-receipt", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--queue", required=True)
    parser.add_argument("--parent", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(prepare(args.api_receipt, args.python, args.queue, args.parent))
    except (OSError, ValueError, KeyError):
        parser.exit(1, "Candidate worker preparation failed; no worker was started.\n")


if __name__ == "__main__":
    main()
