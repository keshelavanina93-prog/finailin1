"""Preparation boundaries; optional original public bytes in a disposable synthetic tenant."""

import importlib.util
import json
import os
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    script = load_script("geosparql_preparation", ROOT / "scripts/prepare-geosparql-profile.py")
    manifest = json.loads(script.MANIFEST.read_bytes())
    retrieval = []
    for item in manifest["artifacts"]:
        # Deliberately non-authentic small test bytes; never claim these are the OGC artifact.
        data = (
            f"<{item['artifact_iri']}>\n"
            f"schema:publisher <{manifest['publisher_iri']}>\n"
            f"schema:license <{manifest['declared_license_iri']}>\n"
            f"{manifest['version_info_prefix']}\n{item['version_iri_turtle']}\n"
        ).encode()
        item.update(sha256=sha256(data).hexdigest(), byte_length=len(data))
        (tmp_path / item["file"]).write_bytes(data)
        retrieval.append(
            {
                "file": item["file"],
                "requested_url": item["source_url"],
                "retrieved_url": item["source_url"],
                "sha256": item["sha256"],
                "byte_length": len(data),
                "retrieved_at": "2026-09-08T01:00:00+00:00",
                "retrieval_time_basis": "SYNTHETIC test timestamp",
            }
        )
    manifest_path = tmp_path / "synthetic-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(script, "MANIFEST", manifest_path)
    (tmp_path / "retrieval-manifest.json").write_text(json.dumps(retrieval), encoding="utf-8")
    return script, tmp_path, manifest


def arguments(script, directory, stage, *extra):
    return script.parser().parse_args([stage, "--artifact-dir", str(directory), *extra])


@pytest.mark.parametrize("stage", ["verify", "publisher", "retain"])
def test_preview_never_uses_runtime_or_claims_review(preparation, stage):
    script, directory, _ = preparation
    client = Mock()
    result = script.run(arguments(script, directory, stage), client)
    assert result["review_performed"] is False
    assert result["state"] in {"LOCAL_ARTIFACT_VERIFIED", "PREVIEW_ONLY"}
    client.request.assert_not_called()
    if stage == "publisher":
        assert result["request"]["retrieval_policy"] == "OFFLINE_RETAINED_ONLY"
        assert result["request"]["supported_formats"] == ["TURTLE"]


@pytest.mark.parametrize("damage", ["bytes", "url", "duplicate", "naive-time"])
def test_provenance_tampering_refuses_before_retention(preparation, damage):
    script, directory, manifest = preparation
    first = manifest["artifacts"][0]
    if damage == "bytes":
        path = directory / first["file"]
        path.write_bytes(path.read_bytes().replace(b"1.1.1", b"1.1.2", 1))
    else:
        path = directory / "retrieval-manifest.json"
        records = json.loads(path.read_bytes())
        if damage == "url":
            records[0]["retrieved_url"] = "https://example.invalid/substitute.ttl"
        elif damage == "duplicate":
            records.append(records[0])
        else:
            records[0]["retrieved_at"] = "2026-09-08T01:00:00"
        path.write_text(json.dumps(records), encoding="utf-8")
    client = Mock()
    with pytest.raises(ValueError):
        script.run(arguments(script, directory, "retain", "--apply"), client)
    client.request.assert_not_called()


def test_exact_pin_reads_reviewed_version_even_with_future_editing_head(preparation):
    from finai_api.domain.semantic_analysis import Pin

    script, _, manifest = preparation
    pin = Pin(resource_id=uuid4(), version_id=uuid4(), content_hash="a" * 64)
    approved = {
        **pin.model_dump(mode="json"),
        "object_type": "ExternalOntologySource",
        "authority_state": "APPROVED",
        "attributes": {"definition": script.publisher_definition(manifest).model_dump(mode="json")},
    }
    future = {**approved, "version_id": str(uuid4()), "content_hash": "b" * 64}
    client = Mock()
    client.request.return_value = httpx.Response(
        200,
        json={
            "resource": future,
            "versions": [future, approved],
        },
    )
    script.verify_publisher(client, pin, manifest)
    client.request.assert_called_once_with("GET", f"resources/{pin.resource_id}")
    altered = deepcopy(approved)
    altered["attributes"]["definition"]["license"] = "substitute license"
    client.request.return_value = httpx.Response(
        200, json={"resource": future, "versions": [altered]}
    )
    with pytest.raises(ValueError, match="publisher pin differs"):
        script.verify_publisher(client, pin, manifest)


def test_retention_receipt_and_explicit_retrieval_time_bind_release(preparation):
    script, directory, manifest = preparation
    client = Mock()
    client.request.side_effect = [
        httpx.Response(
            200,
            json={
                "document_id": "doc_" + item["sha256"],
                "sha256": item["sha256"],
                "byte_length": item["byte_length"],
            },
        )
        for item in manifest["artifacts"]
    ]
    receipt = script.run(arguments(script, directory, "retain", "--apply"), client)
    receipt_path = directory / "retained.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    pin_path = directory / "source.json"
    pin_path.write_text(
        json.dumps(
            {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}
        ),
        encoding="utf-8",
    )
    args = arguments(
        script, directory, "release", "--source-pin", str(pin_path), "--retained", str(receipt_path)
    )
    with pytest.raises(ValueError, match="requires its explicit"):
        script.run(args)
    args.retrieved_at = [
        name + "=" + data["retrieved_at"] for name, data in receipt["retrieval"].items()
    ]
    result = script.run(args)
    assert result["state"] == "PREVIEW_ONLY"
    assert result["request"]["publication_status"] == "DEVELOPMENT"
    assert len(result["request"]["modules"]) == 2
    args.retrieved_at[0] = "geo.ttl=2025-11-19T00:00:00+00:00"
    with pytest.raises(ValueError, match="differs from retained"):
        script.run(args)
    args.retrieved_at = [
        name + "=" + data["retrieved_at"] for name, data in receipt["retrieval"].items()
    ]
    receipt["documents"]["geo.ttl"]["sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from original"):
        script.run(args)


@pytest.mark.parametrize(
    "base", ["https://example.invalid/v1/ontology", "http://127.0.0.1/v1/ontology?redirect=remote"]
)
def test_apply_refuses_remote_or_ambiguous_transport_before_credentials_leave(
    preparation, monkeypatch, capsys, base
):
    import sys

    script, directory, _ = preparation
    factory = Mock()
    monkeypatch.setattr(script.httpx, "Client", factory)
    monkeypatch.setenv("G8_ONTOLOGY_TOKEN", "SYNTHETIC-secret-not-for-output")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare-geosparql-profile.py",
            "publisher",
            "--artifact-dir",
            str(directory),
            "--base-url",
            base,
            "--apply",
        ],
    )
    with pytest.raises(SystemExit) as refusal:
        script.main()
    assert refusal.value.code == 1
    assert "SYNTHETIC-secret-not-for-output" not in capsys.readouterr().err
    factory.assert_not_called()


def test_profile_refuses_substituted_release_graph_before_proposal(preparation):
    script, directory, manifest = preparation
    _, _, _, provenance = script.verify_artifacts(directory)
    pin = {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}
    pin_path = directory / "release-pin.json"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    modules = [
        {
            "source": pin,
            "artifact_iri": item["artifact_iri"],
            "document": {
                "document_id": "doc_" + item["sha256"],
                "sha256": item["sha256"],
                "byte_length": item["byte_length"],
            },
            "format": "TURTLE",
            "owned_namespaces": item["owned_namespaces"],
            "permitted_import_iris": [],
            "source_url": item["source_url"],
            "license": manifest["declared_license_iri"],
            "retrieved_at": provenance[item["file"]]["retrieved_at"],
        }
        for item in manifest["artifacts"]
    ]
    modules[0]["artifact_iri"] = "https://example.invalid/unapproved-graph"
    client = Mock()
    client.request.return_value = httpx.Response(
        200,
        json={
            "release": pin,
            "mode": "CURRENT_RELEASE",
            "definition": {
                "request": {
                    "source": pin,
                    "release_label": manifest["release_label"],
                    "publication_status": "DEVELOPMENT",
                    "modules": modules,
                }
            },
        },
    )
    with pytest.raises(ValueError, match="graphs differ"):
        script.run(
            arguments(script, directory, "profile", "--release-pin", str(pin_path), "--apply"),
            client,
        )
    client.request.assert_called_once_with(
        "POST",
        "external/releases/inspect",
        json={
            "release": pin,
            "mode": "CURRENT_RELEASE",
        },
    )


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1"
    or os.environ.get("G8_NATIVE_STORAGE_TEST") != "1"
    or not os.environ.get("G8_GEOSPARQL_ARTIFACT_DIR"),
    reason="Explicit retained public artifacts and disposable native DB/storage opt-in required",
)
def test_original_public_vocabulary_review_journey_in_synthetic_tenant(tmp_path, monkeypatch):
    import psycopg
    from fastapi.testclient import TestClient
    from finai_api.config import get_settings
    from finai_api.domain.authority import ExactScope
    from finai_api.domain.ontology_catalog import platform_definitions
    from finai_api.domain.review import Principal
    from finai_api.main import app

    script = load_script(
        "geosparql_native_preparation", ROOT / "scripts/prepare-geosparql-profile.py"
    )
    directory = Path(os.environ["G8_GEOSPARQL_ARTIFACT_DIR"])
    manifest, _, _, provenance = script.verify_artifacts(directory)
    tenant = uuid4()
    # This proof cannot accidentally write to a mounted/product database.
    with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
        data_dir = conn.execute("SHOW data_directory").fetchone()[0]
        assert (
            data_dir.replace("\\", "/").lower() == "d:/finai/g8-ci-repair/.finai/data/postgres-ci"
        )
        installer = load_script("geosparql_fixture_installer", ROOT / "scripts/install-ontology.py")
        installer.install(conn, tenant, platform_definitions(tenant))
    maker = Principal(
        actor_id="SYNTHETIC-geosparql-maker",
        display_name="SYNTHETIC public vocabulary maker",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="SYNTHETIC-geosparql-only",
            period="2026-09",
            currency="GEL",
        ),
        permissions=(
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
            "ingest",
        ),
    )
    checker = maker.model_copy(
        update={
            "actor_id": "SYNTHETIC-independent-geosparql-checker",
            "permissions": ("ontology_read", "ontology_review", "ontology_admin"),
        }
    )
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "synthetic-geosparql-maker": maker.model_dump(mode="json"),
                "synthetic-geosparql-checker": checker.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    evidence = {
        "scope": maker.scope.model_dump(mode="json"),
        "fixture": "SYNTHETIC principals; original public OGC bytes",
        "company_facts_created": False,
        "reviews": [],
    }
    try:
        with TestClient(
            app,
            base_url="http://testserver/v1/ontology/",
            headers={
                "Authorization": "Bearer synthetic-geosparql-maker",
            },
        ) as client:

            def review(proposal):
                proposal_id = proposal["proposal"]["proposal_id"]
                assert proposal["decision"] is None
                own = client.post(
                    f"proposals/{proposal_id}/decision",
                    json={
                        "decision": "APPROVED",
                        "rationale": "SYNTHETIC maker must not review own proposal",
                    },
                )
                assert own.status_code == 403
                result = client.post(
                    f"proposals/{proposal_id}/decision",
                    headers={
                        "Authorization": "Bearer synthetic-geosparql-checker",
                    },
                    json={
                        "decision": "APPROVED",
                        "rationale": "SYNTHETIC independent review of original OGC vocabulary only",
                    },
                )
                assert result.status_code == 200, result.text
                assert result.json()["decision"] == "APPROVED"
                evidence["reviews"].append(
                    {
                        "proposal_id": proposal_id,
                        "maker_refused": 403,
                        "independent_review": "APPROVED",
                    }
                )

            def pin_for(resource_id, filename):
                result = client.get(f"resources/{resource_id}")
                assert result.status_code == 200, result.text
                row = result.json()["resource"]
                pin = {key: row[key] for key in ("resource_id", "version_id", "content_hash")}
                path = tmp_path / filename
                path.write_text(json.dumps(pin), encoding="utf-8")
                return path, pin, row

            publisher = script.run(arguments(script, directory, "publisher", "--apply"), client)[
                "response"
            ]
            review(publisher)
            source_path, _, _ = pin_for(
                publisher["proposal"]["mutations"][0]["resource_id"], "source.json"
            )
            receipt = script.run(arguments(script, directory, "retain", "--apply"), client)
            receipt_path = tmp_path / "retained.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            args = arguments(
                script,
                directory,
                "release",
                "--source-pin",
                str(source_path),
                "--retained",
                str(receipt_path),
                "--apply",
            )
            args.retrieved_at = [
                name + "=" + data["retrieved_at"] for name, data in provenance.items()
            ]
            prepared = script.run(args, client)["response"]
            assert prepared["status"] == "REVIEW_REQUIRED", prepared
            assert client.get(f"resources/{prepared['release_id']}").status_code == 404
            review(prepared["proposal"])
            release_path, release_pin, release_row = pin_for(prepared["release_id"], "release.json")
            definition = release_row["attributes"]["definition"]
            assert definition["interpretation"] == "EXTERNAL_MEANING_ONLY"
            assert definition["constraint_validation"] == "NOT_PERFORMED"
            profile = script.run(
                arguments(
                    script, directory, "profile", "--release-pin", str(release_path), "--apply"
                ),
                client,
            )["response"]
            review(profile)
            _, profile_pin, profile_row = pin_for(
                profile["proposal"]["mutations"][0]["resource_id"], "profile.json"
            )
            profile_definition = profile_row["attributes"]["definition"]
            assert profile_definition["business_effect_authorized"] is False
            assert profile_definition["reasoning"] == "NONE"
            assert profile_definition["members"] == [
                {
                    "release": release_pin,
                    "graph_iris": sorted(item["artifact_iri"] for item in manifest["artifacts"]),
                }
            ]
            replay = script.run(args, client)["response"]
            assert replay["release_id"] == prepared["release_id"]
            assert replay["status"] == "ALREADY_RETAINED", replay
            evidence.update(
                release=release_pin,
                profile=profile_pin,
                original_documents=receipt["documents"],
                canonical_dataset=prepared["canonical_dataset"],
                release_replay=replay["status"],
            )
    finally:
        get_settings.cache_clear()
    output = os.environ.get("G8_GEOSPARQL_CAPTURE_PATH")
    if output:
        with script.local_path(Path(output)).open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2)
