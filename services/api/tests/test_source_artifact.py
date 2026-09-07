"""Source artifact provenance tests against a disposable real Git repository."""

import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "source_artifact", Path(__file__).resolve().parents[3] / "scripts/package-source.py"
)
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    artifact.git(root, "init", "--quiet")
    (root / ".gitignore").write_text(".finai/\nignored-secret.env\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"synthetic-test"}\n', encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "source.py").write_text("print('committed')\n", encoding="utf-8")
    artifact.git(root, "add", ".")
    artifact.git(
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
        "Synthetic source",
    )
    return root


def test_deterministic_git_source_excludes_dirty_and_ignored_files(repository):
    original = artifact.package(repository, "HEAD")
    (repository / "nested" / "source.py").write_text("print('dirty')\n", encoding="utf-8")
    (repository / "ignored-secret.env").write_text("SYNTHETIC_NON_SECRET_FIXTURE", encoding="utf-8")
    (repository / "untracked.py").write_text("untracked", encoding="utf-8")
    repeated = artifact.package(repository, "HEAD")
    assert repeated == original
    with zipfile.ZipFile(original["archive"]) as archive:
        assert archive.read("source/nested/source.py") == b"print('committed')\n"
        assert not any("secret" in name or "untracked" in name for name in archive.namelist())


def test_modified_content_and_forged_commit_binding_are_rejected(repository):
    packaged = artifact.package(repository, "HEAD")
    with zipfile.ZipFile(packaged["archive"]) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["source/nested/source.py"] = b"print('tampered')\n"
    target = repository / "tampered.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in members.items():
            artifact.member(archive, name, data)
    with pytest.raises(ValueError, match="integrity"):
        artifact.verify(target)
    manifest = json.loads(members[artifact.MANIFEST])
    item = next(item for item in manifest["files"] if item["path"] == "nested/source.py")
    data = members["source/nested/source.py"]
    item.update(
        bytes=len(data),
        sha256=artifact.digest(data),
        git_blob=artifact.object_hash("blob", data, "sha1"),
    )
    members[artifact.MANIFEST] = artifact.encoded(manifest)
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in members.items():
            artifact.member(archive, name, data)
    with pytest.raises(ValueError, match="Git commit"):
        artifact.verify(target)


def test_git_symbolic_links_are_not_packaged(repository):
    blob = (
        subprocess.run(
            ["git", "-C", str(repository), "hash-object", "-w", "--stdin"],
            input=b"../outside",
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )
    artifact.git(repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},link")
    artifact.git(
        repository,
        "-c",
        "user.name=Artifact Test",
        "-c",
        "user.email=artifact@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Synthetic link",
    )
    with pytest.raises(ValueError, match="links are refused"):
        artifact.package(repository, "HEAD")
