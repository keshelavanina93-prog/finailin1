"""Host path policy retains Windows D: restrictions and cross-host containment."""

import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "packaging_host_policy", Path(__file__).resolve().parents[3] / "scripts/package-web-artifact.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize(
    "host,drive,rejected", [("nt", "C:", True), ("nt", "D:", False), ("posix", "", False)]
)
def test_source_path_uses_host_drive_policy(monkeypatch, host, drive, rejected):
    path = SimpleNamespace(
        parents=(), is_symlink=lambda: False, is_junction=lambda: False,
        resolve=lambda: SimpleNamespace(drive=drive),
    )
    monkeypatch.setattr(builder.source_artifact, "os", SimpleNamespace(name=host))
    if rejected:
        with pytest.raises(ValueError, match="Artifacts must remain on D:"):
            builder.source_artifact.check_path(path)
    else:
        builder.source_artifact.check_path(path)


@pytest.mark.parametrize("host", ["nt", "posix"])
@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_source_link_refusal_is_not_weakened_by_host(monkeypatch, host, kind):
    path = SimpleNamespace(
        parents=(), is_symlink=lambda: kind == "symlink", is_junction=lambda: kind == "junction",
    )
    monkeypatch.setattr(builder.source_artifact, "os", SimpleNamespace(name=host))
    with pytest.raises(ValueError, match="reparse points"):
        builder.source_artifact.check_path(path)


def test_posix_resolution_keeps_native_path_and_strict_existence(monkeypatch):
    monkeypatch.setattr(builder, "os", SimpleNamespace(name="posix"))
    resolved = PurePosixPath("/ci/workspace/dependencies/package")
    path = SimpleNamespace(resolve=Mock(return_value=resolved))
    assert builder.resolved_path(path) == resolved
    path.resolve.assert_called_once_with(strict=True)
    assert builder.within(resolved, [PurePosixPath("/ci/workspace/dependencies")])
    assert not builder.within(resolved, [PurePosixPath("/ci/workspace/other")])


def test_windows_dependency_refuses_foreign_drive(monkeypatch):
    monkeypatch.setattr(builder, "os", SimpleNamespace(name="nt"))
    path = SimpleNamespace(
        absolute=lambda: "/synthetic-path",
        resolve=lambda **kwargs: PureWindowsPath("C:/dependencies/package"),
    )
    with pytest.raises(ValueError, match="Dependencies must remain on D:"):
        builder.resolved_path(path)


@pytest.mark.parametrize("path", ["C:/candidate/receipt.json", "D:/candidate/receipt.json"])
def test_posix_refuses_windows_paths_before_filesystem_access(monkeypatch, path):
    monkeypatch.setattr(builder.source_artifact, "os", SimpleNamespace(name="posix"))
    with pytest.raises(ValueError, match=r"Windows host.*D:"):
        builder.source_artifact.check_path(PureWindowsPath(path))
