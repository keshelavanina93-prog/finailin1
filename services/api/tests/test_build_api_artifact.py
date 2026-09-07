"""Archive build provenance refuses source mutation and altered wheel migrations."""

import base64
import csv
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "g8_build_api", Path(__file__).resolve().parents[3] / "scripts/build-api-artifact.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def fixture(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    entries = {
        "services/api/pyproject.toml": (
            b"[project]\nname='finai-api'\nversion='0.1.0'\nrequires-python='>=3.13'\n"
        ),
        "services/api/migrations/001_example.sql": b"SELECT 1;\n",
        "services/api/src/finai_api/__init__.py": b"",
    }
    files = []
    for name, content in entries.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        files.append({"path": name, "sha256": builder.source_artifact.digest(content)})
    return root, {"files": files}, entries


@pytest.mark.parametrize("change", ["modified", "removed", "generated"])
def test_build_source_must_remain_exactly_the_verified_archive(tmp_path, change):
    root, manifest, _ = fixture(tmp_path)
    builder.verify_source(root, manifest)
    original = root / "services/api/migrations/001_example.sql"
    if change == "modified":
        original.write_bytes(b"SELECT 2;")
    elif change == "removed":
        original.unlink()
    else:
        (root / "generated.py").write_bytes(b"print('not an archived input')")
    with pytest.raises(ValueError, match="source inputs"):
        builder.verify_source(root, manifest)


@pytest.mark.parametrize("corrupt", [None, "sql", "extra", "metadata", "record"])
def test_wheel_migrations_require_exact_archived_content(tmp_path, corrupt):
    root, manifest, entries = fixture(tmp_path)
    wheel = tmp_path / "fixture.whl"
    content = {
        name.replace("services/api/src/", "").replace(
            "services/api/migrations/", "finai_api/migrations/"
        ): data
        for name, data in entries.items()
        if not name.endswith("pyproject.toml")
    }
    info = "finai_api-0.1.0.dist-info/"
    content[info + "METADATA"] = b"Name: finai-api\nVersion: 0.1.0\nRequires-Python: >=3.13\n"
    content[info + "WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    if corrupt == "sql":
        content["finai_api/migrations/001_example.sql"] = b"SELECT 2;"
    elif corrupt == "extra":
        content["finai_api/extra.py"] = b"raise RuntimeError()"
    elif corrupt == "metadata":
        content[info + "METADATA"] = b"Name: unrelated\nVersion: 0.1.0\nRequires-Python: >=3.13\n"
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, data in content.items():
        encoded = (
            base64.urlsafe_b64encode(bytes.fromhex(builder.source_artifact.digest(data)))
            .decode()
            .rstrip("=")
        )
        writer.writerow([name, "sha256=" + encoded, len(data)])
    writer.writerow([info + "RECORD", "", ""])
    content[info + "RECORD"] = record.getvalue().encode()
    if corrupt == "record":
        content[info + "RECORD"] = b""
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in content.items():
            archive.writestr(name, data)
    if corrupt:
        with pytest.raises(ValueError):
            builder.verify_wheel(wheel, root, manifest)
    else:
        assert builder.verify_wheel(wheel, root, manifest)["canonical_sql_files"] == 1


def test_child_build_does_not_inherit_runtime_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("FINAI_ACCESS_TOKENS", "never inherited")
    monkeypatch.setenv("FINAI_DATABASE_URL", "never inherited")
    environment = builder.child_environment(tmp_path, tmp_path / "python.exe")
    assert "FINAI_ACCESS_TOKENS" not in environment and "FINAI_DATABASE_URL" not in environment
    assert environment["PIP_NO_INDEX"] == "1" and environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert Path(environment["TEMP"]).is_relative_to(tmp_path)
