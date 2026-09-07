"""Installed-wheel and editable SQL dependencies retain the same logical hash keys."""

from hashlib import sha256

import pytest

from finai_api.services.function_execution import _migration_dependencies
from finai_api.services.workspace import WorkspaceError


def test_packaged_and_editable_migration_hashes_match(tmp_path):
    project = tmp_path / "project"
    editable = project / "src" / "finai_api"
    editable.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    source = project / "migrations"
    source.mkdir()
    installed = tmp_path / "site-packages" / "finai_api"
    packaged = installed / "migrations"
    packaged.mkdir(parents=True)
    (source / "001_fixture.sql").write_bytes(b"BEGIN;\r\nCOMMIT;\r\n")
    (packaged / "001_fixture.sql").write_bytes(b"BEGIN;\nCOMMIT;\n")
    expected = {"migrations/001_fixture.sql": sha256(b"BEGIN;\nCOMMIT;\n").hexdigest()}
    assert _migration_dependencies(editable) == _migration_dependencies(installed) == expected


def test_missing_packaged_sql_cannot_fall_back_to_unrelated_parent(tmp_path):
    installed = tmp_path / "site-packages" / "finai_api"
    installed.mkdir(parents=True)
    unrelated = tmp_path / "migrations"
    unrelated.mkdir()
    (unrelated / "001_unrelated.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="SQL dependency manifest"):
        _migration_dependencies(installed)


def test_empty_packaged_directory_fails_closed(tmp_path):
    package = tmp_path / "src" / "finai_api"
    (package / "migrations").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    source = tmp_path / "migrations"
    source.mkdir()
    (source / "001_fixture.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="SQL dependency manifest"):
        _migration_dependencies(package)
