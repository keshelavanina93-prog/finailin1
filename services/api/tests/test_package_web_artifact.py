"""Web collection preserves source proof and refuses modified inputs or escaped dependencies."""

import importlib.util
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "web_artifact", Path(__file__).resolve().parents[3] / "scripts/package-web-artifact.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    builder.source_artifact.git(root, "init", "--quiet")
    (root / "package.json").write_text('{"name":"synthetic-packaging-fixture"}', encoding="utf-8")
    builder.source_artifact.git(root, "add", "package.json")
    builder.source_artifact.git(
        root,
        "-c",
        "user.name=Artifact Test",
        "-c",
        "user.email=artifact@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Synthetic packaging fixture",
    )
    archive = Path(builder.source_artifact.package(root, "HEAD")["archive"])
    generated = {
        "apps/web/.next/standalone/apps/web/server.js": b"// synthetic server fixture",
        "apps/web/.next/standalone/node_modules/example/index.js": b"// synthetic dependency",
        "apps/web/.next/static/chunk.js": b"// synthetic static fixture",
        "apps/web/public/brand.txt": b"synthetic public fixture",
        "apps/web/.next/standalone/apps/web/.env.local": b"SYNTHETIC_NOT_A_REAL_SECRET",
    }
    for name, data in generated.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root, archive


def test_collects_exact_inventory_and_committed_source_proof(source, tmp_path):
    root, archive = source
    result = builder.package(root, archive, tmp_path / "artifacts", [], ".next")
    stage = Path(result["artifact_directory"])
    receipt = json.loads((stage / "web-artifact.json").read_text(encoding="utf-8"))
    assert receipt["source"] == builder.source_artifact.verify(archive)
    assert receipt["build_invocation_verified"] is False
    assert receipt["release_accepted"] is False
    assert receipt["excluded_private_paths"] == ["apps/web/.env.local"]
    with zipfile.ZipFile(stage / "web.zip") as packaged:
        assert set(packaged.namelist()) == {
            builder.WEB_MANIFEST,
            "apps/web/server.js",
            "node_modules/example/index.js",
            "apps/web/.next/static/chunk.js",
            "apps/web/public/brand.txt",
        }
        embedded = json.loads(packaged.read(builder.WEB_MANIFEST))
        assert embedded == {
            key: value for key, value in receipt.items() if key not in {"archive", "archive_sha256"}
        }
        for item in receipt["files"]:
            assert builder.source_artifact.digest(packaged.read(item["path"])) == item["sha256"]
    assert builder.source_artifact.file_digest(stage / "web.zip") == receipt["archive_sha256"]


def test_modified_tracked_source_refuses_collection(source, tmp_path):
    root, archive = source
    (root / "package.json").write_text('{"name":"modified"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Tracked build input modified"):
        builder.package(root, archive, tmp_path / "artifacts", [], ".next")
    assert not (tmp_path / "artifacts").exists()


def test_dependency_escape_refused(source, tmp_path):
    root, _ = source
    outside = tmp_path / "outside.js"
    outside.write_text("// excluded root", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the recorded build roots"):
        builder.permitted(outside, [root])


def test_long_windows_dependency_path_keeps_containment(tmp_path):
    root = tmp_path / "dependencies"
    root.mkdir()
    parent = root / ("long-component-" * 8) / ("nested-component-" * 7)
    extended = Path("\\\\?\\" + str(parent.absolute()))
    extended.mkdir(parents=True)
    file = extended / "index.js"
    file.write_bytes(b"// long-path fixture")
    resolved = builder.permitted(file, [root])
    assert resolved.read_bytes() == b"// long-path fixture"
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="outside the recorded build roots"):
        builder.permitted(file, [other])


def junction(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "G8_TEST_LINK": str(path), "G8_TEST_TARGET": str(target)}
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-Command",
            "New-Item -ItemType Junction -Path $env:G8_TEST_LINK "
            "-Target $env:G8_TEST_TARGET | Out-Null",
        ],
        env=environment,
        check=True,
        capture_output=True,
    )


def test_preserves_mapped_dependency_topology_in_hashed_manifest(source, tmp_path):
    root, archive = source
    original = root / "node_modules/example"
    original.mkdir(parents=True)
    (original / "index.js").write_bytes(b"// synthetic dependency")
    link = root / "apps/web/.next/standalone/apps/web/node_modules/example"
    junction(link, original)
    result = builder.package(root, archive, tmp_path / "artifacts", [], ".next")
    with zipfile.ZipFile(Path(result["artifact_directory"]) / "web.zip") as packaged:
        manifest = json.loads(packaged.read(builder.WEB_MANIFEST))
        assert manifest["links"] == [
            {
                "path": "apps/web/node_modules/example",
                "target": "node_modules/example",
                "kind": "DIRECTORY_LINK",
            }
        ]
        assert "apps/web/node_modules/example/index.js" not in packaged.namelist()
        assert "node_modules/example/index.js" in packaged.namelist()


def test_unmapped_dependency_link_is_refused(source, tmp_path):
    root, archive = source
    original = root / "node_modules/untraced"
    original.mkdir(parents=True)
    junction(root / "apps/web/.next/standalone/apps/web/node_modules/untraced", original)
    with pytest.raises((ValueError, FileNotFoundError)):
        builder.package(root, archive, tmp_path / "artifacts", [], ".next")
