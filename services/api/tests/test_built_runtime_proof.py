"""Isolated runtime proof helper checks; no production listeners are touched."""

import importlib.util
import json
import socket
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "g8_built_runtime_proof",
    Path(__file__).resolve().parents[3] / "scripts/verify-built-runtime.py",
)
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


@pytest.mark.parametrize("change", [None, "extra", "hash", "escape"])
def test_web_extraction_matches_exact_receipt(tmp_path, change, monkeypatch):
    # This test exercises receipt/member integrity. The production host-path
    # policy is covered independently; pytest fixtures live under the Windows
    # user temp directory rather than the D:-only runtime root.
    monkeypatch.setattr(proof.source_tools, "check_path", lambda _path: None)
    path = tmp_path / "web.zip"
    name = "../escape.js" if change == "escape" else "apps/web/server.js"
    data = b"console.log('synthetic artifact only')"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, data)
        if change == "extra":
            archive.writestr("unrecorded.js", b"extra")
    receipt = {
        "contract": "g8-web-artifact/2",
        "links": [],
        "archive": "web.zip",
        "archive_sha256": proof.source_tools.file_digest(path),
        "entrypoint": name,
        "files": [
            {
                "path": name,
                "bytes": len(data),
                "sha256": "0" * 64 if change == "hash" else proof.source_tools.digest(data),
            }
        ],
    }
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            proof.WEB_MANIFEST,
            json.dumps(
                {
                    key: value
                    for key, value in receipt.items()
                    if key not in ("archive", "archive_sha256")
                }
            ),
        )
    receipt["archive_sha256"] = proof.source_tools.file_digest(path)
    if change:
        with pytest.raises(ValueError):
            proof.extract_web(receipt, tmp_path / "web-artifact.json", tmp_path / "extracted")
    else:
        entry = proof.extract_web(receipt, tmp_path / "web-artifact.json", tmp_path / "extracted")
        assert entry.read_bytes() == data


def test_occupied_port_is_refused_without_stopping_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(OSError):
            proof.available(port)
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


@pytest.mark.parametrize(
    "links",
    [
        [{"path": "node_modules/a", "target": "../outside", "kind": "DIRECTORY_LINK"}],
        [{"path": "a/b", "target": "a", "kind": "DIRECTORY_LINK"}],
        [
            {"path": "a", "target": "b", "kind": "DIRECTORY_LINK"},
            {"path": "b", "target": "a", "kind": "DIRECTORY_LINK"},
        ],
        [{"path": "apps", "target": "node_modules/real", "kind": "DIRECTORY_LINK"}],
    ],
)
def test_junction_escape_cycles_and_payload_collisions_are_rejected(links):
    with pytest.raises(ValueError):
        proof.validated_links(links, ["apps/web/server.js"])


def test_valid_internal_directory_link_is_preserved():
    links = [
        {
            "path": "apps/web/node_modules/next",
            "target": "node_modules/.pnpm/next/node_modules/next",
            "kind": "DIRECTORY_LINK",
        }
    ]
    assert (
        proof.validated_links(
            links, ["apps/web/server.js", "node_modules/.pnpm/next/node_modules/next/index.js"]
        )
        == links
    )
