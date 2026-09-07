"""Build an immutable G8 source archive from Git objects, never the working tree."""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 20_000
MAX_BYTES = 512 * 1024 * 1024
MANIFEST = "G8-SOURCE-MANIFEST.json"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    ).stdout


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_path(path):
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Artifact paths cannot traverse reparse points")
    if path.resolve().drive.upper() != "D:":
        raise ValueError("Artifacts must remain on D:")


def safe_name(name):
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name != PurePosixPath(name).as_posix()
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(part in (".", "..") or part.endswith((" ", ".")) for part in parts)
        or any(ord(char) < 32 for char in name)
    ):
        raise ValueError("Unsafe source archive path")
    return name


def object_hash(kind, data, algorithm):
    return hashlib.new(
        algorithm, kind.encode() + b" " + str(len(data)).encode() + b"\0" + data
    ).hexdigest()


def tree_hash(files, algorithm):
    root = {}
    for item in files:
        node = root
        parts = item["path"].split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise TypeError("Conflicting Git paths")
        if parts[-1] in node:
            raise ValueError("Duplicate Git path")
        node[parts[-1]] = (item["mode"], item["git_blob"])

    def calculate(node):
        content = bytearray()
        for name, child in sorted(
            node.items(),
            key=lambda pair: (
                pair[0].encode() + (b"/" if isinstance(pair[1], dict) else b"")
            ),
        ):
            mode, identity = (
                ("40000", calculate(child)) if isinstance(child, dict) else child
            )
            content.extend(
                mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(identity)
            )
        return object_hash("tree", bytes(content), algorithm)

    return calculate(root)


@contextmanager
def blobs(root):
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def read(item):
        process.stdin.write((item["git_blob"] + "\n").encode())
        process.stdin.flush()
        header = process.stdout.readline().split()
        if header != [item["git_blob"].encode(), b"blob", str(item["bytes"]).encode()]:
            raise ValueError("Git blob identity differs from the frozen tree")
        data = process.stdout.read(item["bytes"])
        if len(data) != item["bytes"] or process.stdout.read(1) != b"\n":
            raise ValueError("Git blob stream is incomplete")
        return data

    try:
        yield read
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("Git object reader failed")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()


def dependency_role(name):
    if name == "pnpm-lock.yaml":
        return "JAVASCRIPT_LOCK"
    if name.endswith("requirements-local.lock"):
        return "WINDOWS_PYTHON_LOCK"
    if name.endswith(("package.json", "pyproject.toml")):
        return "PACKAGE_DECLARATION"
    if name.startswith("services/api/migrations/") and name.endswith(".sql"):
        return "DATABASE_MIGRATION"
    if name in ("scripts/install-local-minio.ps1", "scripts/g8-workflows.ps1"):
        return "EXTERNAL_RUNTIME_INSTALLATION_INPUT"
    return None


def member(archive, name, data, mode="100644"):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = int(mode, 8) << 16
    info.compress_type = zipfile.ZIP_STORED
    archive.writestr(info, data)


def verify(path):
    check_path(path)
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if (
            len(names) != len(set(names))
            or len(names) > MAX_FILES + 1
            or sum(item.file_size for item in entries) > MAX_BYTES + 16_000_000
            or any(item.compress_type != zipfile.ZIP_STORED for item in entries)
            or archive.getinfo(MANIFEST).file_size > 16_000_000
        ):
            raise ValueError("Artifact inventory is invalid or exceeds its bounds")
        manifest = json.loads(archive.read(MANIFEST))
        if (
            manifest.get("contract") != "g8-source-artifact/1"
            or manifest.get("kind") != "SOURCE_ARTIFACT"
        ):
            raise ValueError("Unsupported artifact contract")
        files = manifest["files"]
        if manifest["git_object_format"] not in ("sha1", "sha256"):
            raise ValueError("Unsupported Git object format")
        if set(names) != {
            MANIFEST,
            *("source/" + safe_name(item["path"]) for item in files),
        }:
            raise ValueError("Archive members differ from the source manifest")
        for item in files:
            data = archive.read("source/" + item["path"])
            if archive.getinfo("source/" + item["path"]).external_attr >> 16 != int(
                item["mode"], 8
            ):
                raise ValueError("Archived file mode differs from its Git mode")
            if (
                item["mode"] not in ("100644", "100755")
                or len(data) != item["bytes"]
                or digest(data) != item["sha256"]
            ):
                raise ValueError("Source artifact content integrity failed")
            if (
                object_hash("blob", data, manifest["git_object_format"])
                != item["git_blob"]
            ):
                raise ValueError("Source does not match its Git blob identity")
        commit_data = base64.b64decode(manifest["commit_object_base64"], validate=True)
        if (
            tree_hash(files, manifest["git_object_format"]) != manifest["tree"]
            or object_hash("commit", commit_data, manifest["git_object_format"])
            != manifest["commit"]
            or commit_data.split(b"\n", 1)[0] != b"tree " + manifest["tree"].encode()
        ):
            raise ValueError("Source tree does not match its Git commit")
        if (
            manifest.get("runnable_release") is not False
            or manifest.get("sbom_complete") is not False
        ):
            raise ValueError(
                "Source artifact cannot establish runnable release or complete SBOM"
            )
        expected_inputs = [
            {
                "path": item["path"],
                "sha256": item["sha256"],
                "role": dependency_role(item["path"]),
            }
            for item in sorted(files, key=lambda item: item["path"])
            if dependency_role(item["path"])
        ]
        if manifest["dependency_inputs"] != expected_inputs:
            raise ValueError("Dependency inputs differ from archived source")
    return {
        "archive_sha256": file_digest(path),
        "commit": manifest["commit"],
        "tree": manifest["tree"],
        "files": len(files),
        "kind": manifest["kind"],
    }


def package(root, ref):
    check_path(root)
    commit = (
        git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        .decode()
        .strip()
    )
    tree = git(root, "rev-parse", commit + "^{tree}").decode().strip()
    object_format = git(root, "rev-parse", "--show-object-format").decode().strip()
    commit_data = git(root, "cat-file", "commit", commit)
    rows = git(root, "ls-tree", "-rz", "--full-tree", "--long", commit).split(b"\0")
    entries = []
    for row in rows:
        if not row:
            continue
        metadata, raw_name = row.split(b"\t", 1)
        mode, kind, blob, size = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError(
                "Source archives currently require regular Git files; links are refused"
            )
        entries.append(
            {
                "path": safe_name(raw_name.decode("utf-8")),
                "mode": mode.decode(),
                "git_blob": blob.decode(),
                "bytes": int(size),
            }
        )
    if len(entries) > MAX_FILES or sum(item["bytes"] for item in entries) > MAX_BYTES:
        raise ValueError("Source artifact exceeds its declared file or byte budget")
    destination = root / ".finai" / "artifacts" / "source"
    check_path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="building-", dir=destination))
    archive_path = stage / "source.zip"
    manifest_path = stage / "manifest.json"
    try:
        dependencies = []
        with (
            zipfile.ZipFile(
                archive_path, "w", compression=zipfile.ZIP_STORED
            ) as archive,
            blobs(root) as read_blob,
        ):
            for item in sorted(entries, key=lambda row: row["path"]):
                data = read_blob(item)
                if len(data) != item["bytes"]:
                    raise ValueError("Git object size changed")
                item["sha256"] = digest(data)
                member(archive, "source/" + item["path"], data, item["mode"])
                role = dependency_role(item["path"])
                if role:
                    dependencies.append(
                        {"path": item["path"], "sha256": item["sha256"], "role": role}
                    )
            manifest = {
                "contract": "g8-source-artifact/1",
                "kind": "SOURCE_ARTIFACT",
                "product": "G8 by NYXCore",
                "commit": commit,
                "tree": tree,
                "git_object_format": object_format,
                "commit_object_base64": base64.b64encode(commit_data).decode(),
                "files": sorted(entries, key=lambda item: item["path"]),
                "dependency_inputs": dependencies,
                "runnable_release": False,
                "sbom_complete": False,
                "build_status": "NOT_BUILT_FROM_THIS_ARCHIVE",
                "working_tree_included": False,
            }
            manifest_bytes = encoded(manifest)
            member(archive, MANIFEST, manifest_bytes)
        manifest_path.write_bytes(manifest_bytes)
        for path in (archive_path, manifest_path):
            with path.open("r+b") as stream:
                os.fsync(stream.fileno())
        result = verify(archive_path)
        final = destination / result["archive_sha256"]
        check_path(final)
        if final.exists():
            if (
                verify(final / "source.zip") != result
                or (final / "manifest.json").read_bytes() != manifest_bytes
            ):
                raise ValueError(
                    "Existing immutable artifact differs; overwrite refused"
                )
        else:
            stage.rename(final)
        return {
            **result,
            "archive": str(final / "source.zip"),
            "manifest": str(final / "manifest.json"),
        }
    finally:
        # Only our exact staging files are removed; unexpected contents prevent cleanup.
        if stage.exists():
            check_path(stage)
            archive_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            stage.rmdir()


def materialize(root, source_archive):
    """Prepare isolated build inputs; never merge into an existing checkout."""
    check_path(root)
    check_path(source_archive)
    parent = root / ".finai" / "artifacts" / "build-inputs"
    check_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="source-", dir=parent))
    # Keep failed inputs for diagnosis, without a success receipt. Never recursively delete.
    snapshot = stage / "source.zip"
    with source_archive.open("rb") as incoming, snapshot.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    proof = verify(snapshot)
    with zipfile.ZipFile(snapshot) as archive:
        manifest = json.loads(archive.read(MANIFEST))
        names = {}
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
            f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
        }
        for item in manifest["files"]:
            parts = item["path"].split("/")
            if any(part.split(".")[0].upper() in reserved for part in parts):
                raise ValueError("Source path uses a reserved Windows device name")
            for index in range(1, len(parts) + 1):
                name = "/".join(parts[:index])
                folded = name.casefold()
                if folded in names and names[folded] != name:
                    raise ValueError("Source paths collide on Windows")
                names[folded] = name
        source = stage / "source"
        source.mkdir()
        for item in manifest["files"]:
            destination = source.joinpath(*item["path"].split("/"))
            check_path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                output.write(archive.read("source/" + item["path"]))
            if file_digest(destination) != item["sha256"]:
                raise ValueError("Materialized source differs from archive")
    receipt = {
        "contract": "g8-build-input/1",
        **proof,
        "source_directory": str(source),
        "status": "VERIFIED_SOURCE_ONLY",
        "build_executed": False,
    }
    with (stage / "build-input.json").open("xb") as output:
        output.write(encoded(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--verify", type=Path)
    operation.add_argument(
        "--materialize",
        type=Path,
        help="Verify and prepare a fresh D-local build input directory",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            materialize(ROOT, args.materialize)
            if args.materialize
            else verify(args.verify)
            if args.verify
            else package(ROOT, args.ref),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
