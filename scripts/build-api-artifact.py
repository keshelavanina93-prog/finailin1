"""Build an API wheel offline from a verified committed source artifact."""

import argparse
import base64
import csv
import importlib.util
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "g8_source_artifact", ROOT / "scripts/package-source.py"
)
source_artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_artifact)
BUILD_TOOLS = (
    "pip",
    "hatchling",
    "packaging",
    "pathspec",
    "pluggy",
    "trove-classifiers",
    "editables",
)


def verify_source(source, manifest):
    expected = {item["path"]: item["sha256"] for item in manifest["files"]}
    actual = {}
    for path in source.rglob("*"):
        # The source directory is already checked and materialized by
        # package-source.materialize(). This verifier is also used with
        # ordinary pytest fixtures outside D:, so reapplying the deployment
        # drive policy here would hide content-integrity failures behind an
        # unrelated host-path error. Reparse points remain forbidden.
        if path.is_symlink() or path.is_junction():
            raise ValueError("Build source cannot traverse reparse points")
        if path.is_file():
            actual[path.relative_to(source).as_posix()] = source_artifact.file_digest(
                path
            )
    if actual != expected:
        raise ValueError("Build modified, removed or generated source inputs")


def verify_wheel(wheel, source, manifest):
    project = tomllib.loads(
        (source / "services/api/pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    name = re.sub(r"[-_.]+", "_", project["name"])
    info = f"{name}-{project['version']}.dist-info/"
    metadata_members = {info + suffix for suffix in ("METADATA", "WHEEL", "RECORD")}
    package_members = {
        item["path"].removeprefix("services/api/src/"): item["sha256"]
        for item in manifest["files"]
        if item["path"].startswith("services/api/src/finai_api/")
    }
    expected = {
        item["path"].removeprefix("services/api/migrations/"): item["sha256"]
        for item in manifest["files"]
        if item["path"].startswith("services/api/migrations/")
        and item["path"].endswith(".sql")
    }
    if not expected:
        raise ValueError("Canonical migration inputs are absent")
    with zipfile.ZipFile(wheel) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Wheel contains duplicate members")
        allowed = (
            set(package_members)
            | metadata_members
            | {"finai_api/migrations/" + key for key in expected}
        )
        if set(archive.namelist()) != allowed:
            raise ValueError(
                "Wheel payload inventory differs from archived package inputs"
            )
        metadata = Parser().parsestr(archive.read(info + "METADATA").decode("utf-8"))
        wheel_metadata = Parser().parsestr(archive.read(info + "WHEEL").decode("utf-8"))
        if (
            metadata.get_all("Name") != [project["name"]]
            or metadata.get_all("Version") != [project["version"]]
            or metadata.get_all("Requires-Python") != [project["requires-python"]]
            or wheel_metadata.get_all("Tag") != ["py3-none-any"]
            or wheel_metadata.get("Root-Is-Purelib") != "true"
        ):
            raise ValueError(
                "Wheel distribution metadata differs from archived project"
            )
        records = list(
            csv.reader(io.StringIO(archive.read(info + "RECORD").decode("utf-8")))
        )
        if len(records) != len(allowed) or {row[0] for row in records} != allowed:
            raise ValueError("Wheel RECORD inventory mismatch")
        for row in records:
            if len(row) != 3:
                raise ValueError("Invalid wheel RECORD row")
            if row[0] == info + "RECORD":
                if row[1:] != ["", ""]:
                    raise ValueError("Wheel RECORD self-entry is invalid")
                continue
            data = archive.read(row[0])
            hashed = (
                base64.urlsafe_b64encode(bytes.fromhex(source_artifact.digest(data)))
                .decode()
                .rstrip("=")
            )
            if row[1:] != ["sha256=" + hashed, str(len(data))]:
                raise ValueError("Wheel RECORD content mismatch")
        actual = {
            name.removeprefix("finai_api/migrations/"): source_artifact.digest(
                archive.read(name)
            )
            for name in archive.namelist()
            if name.startswith("finai_api/migrations/") and name.endswith(".sql")
        }
        if actual != expected:
            raise ValueError("Wheel migrations differ from canonical archived inputs")
        for name, expected_hash in package_members.items():
            if source_artifact.digest(archive.read(name)) != expected_hash:
                raise ValueError("Wheel package contents differ from archived inputs")
    return {
        "canonical_sql_files": len(expected),
        "migration_sha256": expected,
        "python_source_matches_archive": True,
        "package_inventory_and_bytes_match_archive": True,
        "metadata_checks": [
            "NAME",
            "VERSION",
            "REQUIRES_PYTHON",
            "WHEEL_TAG",
            "RECORD",
        ],
        "requires_dist_metadata_verified": False,
    }


def child_environment(stage, python):
    environment = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "COMSPEC")
        if key in os.environ
    }
    temp = stage / "tmp"
    cache = stage / "cache"
    temp.mkdir()
    cache.mkdir()
    environment.update(
        {
            "TEMP": str(temp),
            "TMP": str(temp),
            "XDG_CACHE_HOME": str(cache),
            "PIP_CACHE_DIR": str(cache),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": str(python.parent),
        }
    )
    return environment


def run(python, args, stage, environment):
    completed = subprocess.run(
        [str(python), "-B", "-I", *args],
        cwd=stage,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode:
        raise ValueError("Offline build subprocess failed; no success receipt retained")
    return completed.stdout


def build(root, archive, python):
    for path in (root, archive, python):
        source_artifact.check_path(path)
    if not python.is_file():
        raise ValueError("Explicit D-resident Python executable is required")
    authorized = source_artifact.verify(archive)
    # Only committed history already reachable from this authorized repository is executable input.
    source_artifact.git(
        root, "merge-base", "--is-ancestor", authorized["commit"], "HEAD"
    )
    prepared = source_artifact.materialize(root, archive)
    if prepared["archive_sha256"] != authorized["archive_sha256"]:
        raise ValueError("Archive changed before materialization")
    source = Path(prepared["source_directory"])
    snapshot = source.parent / "source.zip"
    with zipfile.ZipFile(snapshot) as frozen:
        manifest = json.loads(frozen.read(source_artifact.MANIFEST))
    verify_source(source, manifest)
    parent = root / ".finai/artifacts/api-builds"
    source_artifact.check_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="build-", dir=parent))
    environment = child_environment(stage, python)
    tools = json.loads(
        run(
            python,
            [
                "-c",
                (
                    "import json,platform,sys,importlib.metadata as m; "
                    "assert sys.version_info[:3]==(3,13,14) and sys.platform=='win32' and platform.machine()=='AMD64'; "
                    f"print(json.dumps({{n:m.version(n) for n in {BUILD_TOOLS!r}}}))"
                ),
            ],
            stage,
            environment,
        )
    )
    lock = source / "services/api/requirements-local.lock"
    pins = dict(
        re.findall(
            r"^([A-Za-z0-9_.-]+)==([^\s;]+)",
            lock.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    if any(pins.get(name) != version for name, version in tools.items()):
        raise ValueError(
            "Installed build tooling differs from the archived dependency lock"
        )
    wheels = stage / "wheels"
    wheels.mkdir()
    run(
        python,
        [
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--wheel-dir",
            str(wheels),
            str(source / "services/api"),
            "--quiet",
        ],
        stage,
        environment,
    )
    verify_source(source, manifest)
    if source_artifact.verify(snapshot)["archive_sha256"] != prepared["archive_sha256"]:
        raise ValueError("Frozen archive changed during build")
    products = list(wheels.iterdir())
    if len(products) != 1 or products[0].suffix != ".whl":
        raise ValueError("Expected exactly one built API wheel")
    wheel = products[0]
    contents = verify_wheel(wheel, source, manifest)
    receipt = {
        "contract": "g8-api-build-artifact/1",
        "kind": "API_WHEEL_BUILD",
        "archive_sha256": prepared["archive_sha256"],
        "commit": prepared["commit"],
        "tree": prepared["tree"],
        "source_directory": str(source),
        "source_unchanged_after_build": True,
        "pyproject_sha256": source_artifact.file_digest(
            source / "services/api/pyproject.toml"
        ),
        "dependency_lock_sha256": source_artifact.file_digest(lock),
        "build_tool_versions": tools,
        "build_script_sha256": source_artifact.file_digest(Path(__file__).resolve()),
        "source_verifier_sha256": source_artifact.file_digest(
            ROOT / "scripts/package-source.py"
        ),
        "python_executable": str(python),
        "target": "CPython3.13.14-Windows-AMD64",
        "wheel": str(wheel),
        "wheel_sha256": source_artifact.file_digest(wheel),
        **contents,
        "dependency_downloads_disabled": True,
        "network_isolation": False,
        "runtime_verified": False,
        "release_accepted": False,
        "sbom_complete": False,
    }
    with (stage / "build-receipt.json").open("xb") as output:
        output.write(source_artifact.encoded(receipt))
        output.flush()
        os.fsync(output.fileno())
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            build(ROOT, args.archive.absolute(), args.python.absolute()), indent=2
        )
    )


if __name__ == "__main__":
    main()
