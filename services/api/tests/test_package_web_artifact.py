"""Web collection preserves source proof and refuses modified inputs or escaped dependencies."""

import importlib.util
import json
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
    builder.source_artifact.git(root, "-c", "user.name=Artifact Test", "-c",
        "user.email=artifact@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "--quiet", "-m", "Synthetic packaging fixture")
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
            "apps/web/server.js", "node_modules/example/index.js",
            "apps/web/.next/static/chunk.js", "apps/web/public/brand.txt",
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
