"""Collect standalone Next output from verified committed inputs; not release acceptance."""

import argparse
import importlib.util
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("source_artifact", ROOT / "scripts/package-source.py")
source_artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_artifact)
MAX_FILES = 100_000
MAX_BYTES = 2_000_000_000


def verify_inputs(source, manifest):
    """Generated directories do not replace verification of any tracked input."""
    for item in manifest["files"]:
        path = source / source_artifact.safe_name(item["path"])
        source_artifact.check_path(path)
        if not path.is_file() or source_artifact.file_digest(path) != item["sha256"]:
            raise ValueError("Tracked build input modified or missing: " + item["path"])


def within(path, roots):
    return any(path.is_relative_to(root) for root in roots)


def resolved_path(path):
    prefix = "\\\\?\\"
    raw = str(path.absolute())
    if re.match(r"^[A-Za-z]:", raw):
        path = Path(prefix + raw)
    resolved = path.resolve(strict=True)
    value = str(resolved)
    if value.startswith(prefix):
        value = value[4:]
    if not re.match(r"^D:[\\/]", value, re.IGNORECASE):
        raise ValueError("Dependencies must remain on D:")
    return Path(prefix + value)


def permitted(path, roots):
    resolved = resolved_path(path)
    if not within(resolved, [resolved_path(root) for root in roots]):
        raise ValueError("Dependency resolves outside the recorded build roots: " + str(path))
    info = path.lstat()
    if (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            and not path.is_symlink() and not path.is_junction()):
        raise ValueError("Unsupported reparse point: " + str(path))
    if not resolved.is_file() and not resolved.is_dir():
        raise ValueError("Only regular files and directories may be packaged: " + str(path))
    return resolved


def private(name):
    lower = name.lower()
    return lower == ".env" or lower.startswith(".env.") or lower in {
        ".npmrc", ".pnpmrc", ".netrc", "credentials", "credentials.json"
    } or lower.endswith((".pem", ".key", ".p12", ".pfx"))


def package(source, archive, output_root, dependency_roots, build_directory):
    for path in (source, archive, output_root, *dependency_roots):
        source_artifact.check_path(path)
    source = source.resolve(strict=True)
    provenance = source_artifact.verify(archive)
    with zipfile.ZipFile(archive) as saved:
        manifest = json.loads(saved.read(source_artifact.MANIFEST))
    verify_inputs(source, manifest)
    roots = [resolved_path(source), *(resolved_path(path) for path in dependency_roots)]
    standalone = source / "apps/web" / build_directory / "standalone"
    static = source / "apps/web" / build_directory / "static"
    server = standalone / "apps/web/server.js"
    if not server.is_file() or not static.is_dir():
        raise ValueError("Completed standalone server and static output are required")
    output_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="web-artifact-", dir=output_root))
    payload = stage / "web.zip"
    files, excluded, visited_names = [], [], set()
    total = 0
    with zipfile.ZipFile(payload, "x", compression=zipfile.ZIP_STORED) as target:
        def collect(path, destination, ancestors=()):
            nonlocal total
            resolved = permitted(path, roots)
            if private(path.name):
                excluded.append(destination)
                return
            if resolved.is_dir():
                if resolved in ancestors:
                    raise ValueError("Dependency directory cycle detected")
                for child in sorted(resolved.iterdir(), key=lambda item: item.name.casefold()):
                    collect(child, destination + "/" + child.name if destination else child.name, (*ancestors, resolved))
                return
            destination = source_artifact.safe_name(destination)
            folded = destination.casefold()
            if folded in visited_names:
                raise ValueError("Duplicate artifact destination: " + destination)
            visited_names.add(folded)
            before = resolved.stat()
            if len(files) >= MAX_FILES or total + before.st_size > MAX_BYTES:
                raise ValueError("Web artifact exceeds bounded inventory")
            data = resolved.read_bytes()
            after = resolved.stat()
            if (permitted(path, roots) != resolved
                    or (after.st_size, after.st_mtime_ns, after.st_ino)
                    != (before.st_size, before.st_mtime_ns, before.st_ino)):
                raise ValueError("Build output changed during collection")
            total += len(data)
            source_artifact.member(target, destination, data)
            root_index = next(index for index, root in enumerate(roots) if resolved.is_relative_to(root))
            files.append({"path": destination, "sha256": source_artifact.digest(data), "bytes": len(data),
                          "input_root": root_index, "input_path": resolved.relative_to(roots[root_index]).as_posix()})

        collect(standalone, "")
        collect(static, "apps/web/" + build_directory + "/static")
        public = source / "apps/web/public"
        if public.is_dir():
            collect(public, "apps/web/public")
    verify_inputs(source, manifest)
    receipt = {
        "contract": "g8-web-artifact/1", "kind": "WEB_BUILD_ARTIFACT",
        "status": "VERIFIED_INPUTS_STANDALONE_COLLECTED", "source": provenance,
        "archive_sha256": source_artifact.file_digest(payload), "archive": payload.name,
        "entrypoint": "apps/web/server.js", "build_directory": build_directory,
        "input_roots": [str(root) for root in roots], "files": files,
        "excluded_private_paths": excluded, "bytes": total,
        "build_invocation_verified": False, "runnable_release": False,
        "release_accepted": False, "sbom_complete": False,
        "limitations": ["Collection verifies tracked inputs and collected bytes, not build invocation provenance.",
                        "Environment values embedded by the build are not established secret-free by file exclusion.",
                        "No runtime or release acceptance is established."]
    }
    (stage / "web-artifact.json").write_bytes(source_artifact.encoded(receipt))
    return {"artifact_directory": str(stage), "archive_sha256": receipt["archive_sha256"],
            "files": len(files), "bytes": total, "source_commit": provenance["commit"], "status": receipt["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, action="append", default=[])
    parser.add_argument("--build-directory", default=".next")
    args = parser.parse_args()
    if not re.fullmatch(r"\.next(?:-[a-z0-9-]+)?", args.build_directory):
        parser.error("Build directory must be a local .next directory")
    print(json.dumps(package(args.source.absolute(), args.source_archive.absolute(),
                             args.output_root.absolute(), [path.absolute() for path in args.dependency_root],
                             args.build_directory), indent=2))


if __name__ == "__main__":
    main()
