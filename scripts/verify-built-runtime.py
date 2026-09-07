"""GET-only isolated HTTP verification of exact built API and standalone web artifacts."""

import argparse
import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WEB_MANIFEST = "G8-WEB-MANIFEST.json"
spec = importlib.util.spec_from_file_location(
    "g8_source_verifier", ROOT / "scripts/package-source.py"
)
source_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_tools)


def available(port):
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", port))


def extract_web(receipt, receipt_path, destination):
    archive = receipt_path.parent / receipt["archive"]
    source_tools.check_path(archive)
    if source_tools.file_digest(archive) != receipt["archive_sha256"]:
        raise ValueError("Web archive hash mismatch")
    entries = receipt["files"]
    names = [source_tools.safe_name(row["path"]) for row in entries]
    if len(names) > 100_000 or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Web archive inventory invalid")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if any(
        part.split(".")[0].upper() in reserved
        for name in names
        for part in name.split("/")
    ):
        raise ValueError("Reserved Windows artifact path")
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if (
            len(members) != len(names) + 1
            or {row.filename for row in members} != set(names) | {WEB_MANIFEST}
            or sum(row.file_size for row in members) > 2_000_000_000
        ):
            raise ValueError("Web archive members differ from receipt")
        if zipped.getinfo(WEB_MANIFEST).file_size > 32_000_000:
            raise ValueError("Web manifest exceeds its size bound")
        embedded = json.loads(zipped.read(WEB_MANIFEST))
        if embedded != {
            key: value
            for key, value in receipt.items()
            if key not in ("archive", "archive_sha256")
        }:
            raise ValueError("Embedded web manifest differs from receipt")
        if embedded.get("contract") != "g8-web-artifact/2":
            raise ValueError("Internal link restoration requires web artifact v2")
        links = validated_links(embedded.get("links", []), names)
        for row in entries:
            info = zipped.getinfo(row["path"])
            mode = info.external_attr >> 16
            if (
                info.is_dir()
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
            ):
                raise ValueError("Only regular web artifact files may execute")
            data = zipped.read(info)
            if len(data) != row["bytes"] or source_tools.digest(data) != row["sha256"]:
                raise ValueError("Web artifact member integrity mismatch")
            target = destination.joinpath(*row["path"].split("/"))
            source_tools.check_path(target)
            io_target = (
                Path("\\\\?\\" + str(target.absolute())) if os.name == "nt" else target
            )
            io_target.parent.mkdir(parents=True, exist_ok=True)
            with io_target.open("xb") as output:
                output.write(data)
    restore_links(destination, links)
    entrypoint = source_tools.safe_name(receipt["entrypoint"])
    if entrypoint not in names:
        raise ValueError("Web entrypoint is not in the verified artifact")
    return destination / entrypoint


def validated_links(links, files):
    if not isinstance(links, list) or len(links) > 100_000:
        raise ValueError("Invalid link inventory")
    paths = []
    for link in links:
        if set(link) != {"path", "target", "kind"} or link["kind"] != "DIRECTORY_LINK":
            raise ValueError("Only declared internal directory links are permitted")
        paths.append(source_tools.safe_name(link["path"]).casefold())
        source_tools.safe_name(link["target"])
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate web links")
    file_paths = [name.casefold() for name in files]
    for link in links:
        name, target = link["path"].casefold(), link["target"].casefold()
        if (
            name == target
            or name.startswith(target + "/")
            or target.startswith(name + "/")
            or any(target == alias or target.startswith(alias + "/") for alias in paths)
            or any(alias != name and alias.startswith(name + "/") for alias in paths)
            or any(
                file == name
                or file.startswith(name + "/")
                or name.startswith(file + "/")
                for file in file_paths
            )
        ):
            raise ValueError("Web link creates an ancestor, cycle or input collision")
    return links


def restore_links(destination, links):
    if not links:
        return
    if os.name != "nt":
        raise ValueError(
            "This verified runtime supports Windows directory junctions only"
        )
    prepared = []
    for link in links:
        path = destination.joinpath(*link["path"].split("/"))
        target = destination.joinpath(*link["target"].split("/"))
        source_tools.check_path(path)
        source_tools.check_path(target)
        if not target.is_dir() or path.exists():
            raise ValueError(
                "Web junction requires a physical retained target and absent alias"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        prepared.append({"path": str(path), "target": str(target)})
    specification = destination.parent / "junctions.json"
    source_tools.check_path(specification)
    with specification.open("x", encoding="utf-8") as stream:
        json.dump(prepared, stream)
    command = (
        "$ErrorActionPreference='Stop'; "
        "$taskLinks=Get-Content -LiteralPath $env:G8_RUNTIME_JUNCTION_SPEC -Raw | ConvertFrom-Json; "
        "foreach($taskLink in $taskLinks){ "
        "New-Item -ItemType Junction -Path $taskLink.path -Target $taskLink.target | Out-Null }"
    )
    executable = shutil.which("pwsh")
    if not executable:
        raise ValueError(
            "PowerShell runtime for verified junction restoration is unavailable"
        )
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "COMSPEC")
        if key in os.environ
    }
    environment["G8_RUNTIME_JUNCTION_SPEC"] = str(specification)
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        check=False,
        timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise ValueError("Verified internal junction restoration failed")
    for row in prepared:
        path, target = Path(row["path"]), Path(row["target"])
        if not path.is_junction() or path.resolve() != target.resolve():
            raise ValueError("Restored junction does not match its verified target")


def verify_installed(python, wheel, cwd):
    command = "import importlib.metadata as m; print(m.distribution('finai-api').locate_file('finai_api').resolve())"
    result = subprocess.run(
        [
            str(python),
            "-B",
            "-I",
            "-X",
            "pycache_prefix=" + str(cwd / "probe-cache"),
            "-c",
            command,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    package = Path(result.stdout.strip())
    source_tools.check_path(package)
    if not package.is_relative_to(python.parent.parent / "Lib/site-packages"):
        raise ValueError("API imports editable or unexpected package")
    with zipfile.ZipFile(wheel) as archive:
        expected = {
            name.removeprefix("finai_api/"): source_tools.digest(archive.read(name))
            for name in archive.namelist()
            if name.startswith("finai_api/")
        }
    actual = {}
    for path in package.rglob("*"):
        source_tools.check_path(path)
        if path.is_file() and path.suffix != ".pyc":
            actual[path.relative_to(package).as_posix()] = source_tools.file_digest(
                path
            )
    if not expected or actual != expected:
        raise ValueError("Installed API differs from selected wheel")
    return str(package)


def stop_owned(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_ready(client, url, process):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError("Owned isolated runtime exited before readiness")
        try:
            response = client.get(url)
            if response.status_code == 200:
                return response
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    raise ValueError("Isolated HTTP runtime did not become ready")


def verify(api_receipt_path, web_receipt_path, python, node):
    for path in (api_receipt_path, web_receipt_path, python, node):
        source_tools.check_path(path)
    api = json.loads(api_receipt_path.read_text(encoding="utf-8"))
    web = json.loads(web_receipt_path.read_text(encoding="utf-8"))
    wheel = Path(api["wheel"])
    source_tools.check_path(wheel)
    if source_tools.file_digest(wheel) != api["wheel_sha256"]:
        raise ValueError("API wheel hash mismatch")
    parent = ROOT / ".finai/runtime-proof"
    source_tools.check_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="http-", dir=parent))
    installed = verify_installed(python, wheel, stage)
    server = extract_web(web, web_receipt_path, stage / "web")
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, grant = next(
        (token, grant)
        for token, grant in grants.items()
        if "read" in grant.get("permissions", []) and "scope" in grant
    )
    available(8063)
    available(3063)
    environment = dict(os.environ)
    environment.update(
        {
            "FINAI_API_URL": "http://127.0.0.1:8063",
            "PORT": "3063",
            "HOSTNAME": "127.0.0.1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    environment.pop("PYTHONPATH", None)
    environment.pop("NODE_OPTIONS", None)
    for name in ("tmp", "cache"):
        (stage / name).mkdir()
    environment.update(
        {
            "TEMP": str(stage / "tmp"),
            "TMP": str(stage / "tmp"),
            "XDG_CACHE_HOME": str(stage / "cache"),
        }
    )
    processes = []
    statuses = {}
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        commands = [
            [
                str(python),
                "-B",
                "-I",
                "-X",
                "pycache_prefix=" + str(stage / "cache"),
                "-m",
                "uvicorn",
                "finai_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8063",
                "--no-access-log",
                "--log-level",
                "error",
            ],
            [str(node), str(server)],
        ]
        for command in commands:
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=stage,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
            )
        with httpx.Client(
            timeout=10, trust_env=False, follow_redirects=False
        ) as client:
            ready = wait_ready(client, "http://127.0.0.1:8063/ready", processes[0])
            home = wait_ready(client, "http://127.0.0.1:3063/", processes[1])
            if "G8" not in home.text:
                raise ValueError("Built web root does not identify G8")
            denied = client.get("http://127.0.0.1:3063/api/readiness")
            headers = {"Authorization": "Bearer " + token}
            allowed = client.get("http://127.0.0.1:3063/api/readiness", headers=headers)
            session = client.get(
                "http://127.0.0.1:3063/api/workspace/session", headers=headers
            )
            if (
                denied.status_code != 401
                or allowed.status_code != 200
                or session.status_code != 200
            ):
                raise ValueError("Built web authentication/proxy checks failed")
            if allowed.json() != ready.json():
                raise ValueError("Built web readiness differs from isolated API")
            if (
                session.json().get("actor_id") != grant["actor_id"]
                or session.json().get("scope") != grant["scope"]
            ):
                raise ValueError("Built web session differs from authorized principal")
            statuses = {
                "api_ready": ready.status_code,
                "web_root": home.status_code,
                "web_readiness_unauthorized": denied.status_code,
                "web_readiness_authorized": allowed.status_code,
                "web_session_authorized": session.status_code,
            }
    finally:
        for process in reversed(processes):
            stop_owned(process)
    proof = {
        "contract": "g8-built-http-verification/1",
        "api_wheel_sha256": api["wheel_sha256"],
        "api_source_archive_sha256": api["archive_sha256"],
        "api_source_commit": api["commit"],
        "web_archive_sha256": web["archive_sha256"],
        "web_source": web["source"],
        "web_build_invocation_verified": web["build_invocation_verified"],
        "installed_api_package": installed,
        "python_executable_sha256": source_tools.file_digest(python),
        "node_executable_sha256": source_tools.file_digest(node),
        "http_statuses": statuses,
        "owned_processes_stopped": all(
            process.poll() is not None for process in processes
        ),
        "requests": "GET_ONLY",
        "worker_execution_verified": False,
        "release_accepted": False,
    }
    (stage / "http-verification.json").write_bytes(source_tools.encoded(proof))
    return {**proof, "evidence_path": str(stage / "http-verification.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("api-receipt", "web-receipt", "python", "node"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                *(
                    path.absolute()
                    for path in (
                        args.api_receipt,
                        args.web_receipt,
                        args.python,
                        args.node,
                    )
                )
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
