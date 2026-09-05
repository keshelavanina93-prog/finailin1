import io
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from finai_api import evidence_objects
from finai_api.domain.authority import ExactScope


class ObjectClient:
    def __init__(self) -> None:
        self.objects: dict[str, list[bytes]] = {}
        self.puts: list[dict[str, Any]] = []
        self.corrupt = False

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        assert kwargs["IfNoneMatch"] == "*"
        if kwargs["Key"] in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        self.objects[kwargs["Key"]] = [kwargs["Body"]]
        return {"VersionId": "1"}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        versions = self.objects[kwargs["Key"]]
        index = int(kwargs.get("VersionId", len(versions))) - 1
        content = b"corrupt" if self.corrupt else versions[index]
        return {
            "Body": io.BytesIO(content),
            "ContentLength": len(content),
            "VersionId": str(index + 1),
        }


@pytest.fixture
def object_store(monkeypatch: pytest.MonkeyPatch) -> tuple[ObjectClient, ExactScope]:
    client = ObjectClient()
    monkeypatch.setattr(evidence_objects, "_client", lambda: client)
    return client, ExactScope(
        tenant_id=uuid4(), legal_entity_id="company-a", period="2026-08", currency="GEL"
    )


def test_create_only_replay_and_version_pinned_reads(
    object_store: tuple[ObjectClient, ExactScope],
) -> None:
    client, scope = object_store
    content = "\ufeffaccount_code,debit,credit\r\n001,1,1\r\n".encode()
    metadata = evidence_objects.preserve(scope, content, sha256(content).hexdigest())
    assert metadata == evidence_objects.preserve(scope, content, sha256(content).hexdigest())
    assert len(client.objects[metadata.object_key]) == 1
    assert metadata.version_id == "1"
    assert evidence_objects.read(scope, metadata) == content
    # A privileged external writer adding a later version cannot alter a pinned receipt.
    client.objects[metadata.object_key].append(b"later external overwrite")
    assert evidence_objects.read(scope, metadata) == content


def test_hash_and_length_corruption_fail_closed(
    object_store: tuple[ObjectClient, ExactScope],
) -> None:
    client, scope = object_store
    content = b"x,y\n001,2\n"
    metadata = evidence_objects.preserve(scope, content, sha256(content).hexdigest())
    client.corrupt = True
    with pytest.raises(evidence_objects.EvidenceStoreUnavailable, match="integrity"):
        evidence_objects.read(scope, metadata)
    with pytest.raises(evidence_objects.EvidenceStoreUnavailable, match="integrity"):
        evidence_objects.preserve(scope, content, sha256(content).hexdigest())


def test_scope_key_and_input_hash_are_verified(
    object_store: tuple[ObjectClient, ExactScope],
) -> None:
    client, scope = object_store
    content = b"source"
    metadata = evidence_objects.preserve(scope, content, sha256(content).hexdigest())
    for changed in (
        {"legal_entity_id": "company-b"},
        {"period": "2026-07"},
        {"tenant_id": uuid4()},
    ):
        with pytest.raises(evidence_objects.EvidenceStoreUnavailable, match="scope"):
            evidence_objects.read(scope.model_copy(update=changed), metadata)
    with pytest.raises(evidence_objects.EvidenceStoreUnavailable, match="integrity"):
        evidence_objects.preserve(scope, content, "0" * 64)
    assert len(client.puts) == 1
