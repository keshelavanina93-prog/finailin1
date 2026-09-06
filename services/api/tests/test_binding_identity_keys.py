"""Long source identifiers must remain distinct without rewriting accepted identities."""

from uuid import uuid4, uuid5

from test_canonical_binding_identity import prepared as prepared

from finai_api.services import ontology_definitions
from finai_api.services.binding_identity import source_identity_key
from finai_api.services.workspace import WorkspaceError


def test_long_source_keys_publish_distinct_bounded_identities(prepared, monkeypatch):
    prepared.binding["attributes"]["definition"]["identity_mode"] = "SOURCE_KEY"

    def missing(*_):
        raise WorkspaceError(404, "No existing source identity")

    monkeypatch.setattr(ontology_definitions.resources, "get_resource", missing)
    prefix = "source-company-" + "ა" * 250
    prepared.row["attributes"]["company_id"] = prefix + "A"
    first = prepared.prepare().mutations[0]
    prepared.row["attributes"]["company_id"] = prefix + "B"
    second = prepared.prepare().mutations[0]
    assert first.resource_id != second.resource_id
    assert first.identity_key != second.identity_key
    assert len(first.identity_key) <= 256 and len(second.identity_key) <= 256
    assert first.resource_id == uuid5(prepared.binding["resource_id"], prefix + "A")


def test_existing_truncated_key_is_preserved_on_update(prepared):
    prepared.binding["attributes"]["definition"]["identity_mode"] = "SOURCE_KEY"
    source_key = "original-" + "x" * 300
    identity = uuid5(prepared.binding["resource_id"], source_key)
    legacy_key = f"binding:{prepared.binding['resource_id']}:{source_key}"[:256]
    prepared.current.update(resource_id=str(identity), identity_key=legacy_key)
    prepared.row["attributes"]["company_id"] = source_key
    update = prepared.prepare().mutations[0]
    assert update.resource_id == identity
    assert update.identity_key == legacy_key
    assert str(update.expected_version_id) == prepared.current["version_id"]


def test_short_and_digest_keys_use_disjoint_namespaces():
    binding = uuid4()
    assert source_identity_key(binding, "001") == f"binding:{binding}:001"
    digest_key = source_identity_key(binding, "x" * 300)
    digest = digest_key.rsplit(":", 1)[1]
    assert digest_key != source_identity_key(binding, "sha256:" + digest)
