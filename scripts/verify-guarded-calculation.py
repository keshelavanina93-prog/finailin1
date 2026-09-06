"""Opt-in real storage/API/restart journey using an explicitly synthetic retained CSV.

Run after scripts/load-local.ps1. Writes isolated canonical fixtures and D: evidence;
never grants financial certification or changes an existing business resource.
"""

import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import httpx
from finai_api.domain.authority import ExactScope
from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import (
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import (
    ontology_definitions,
    resource_lifecycle,
    resources,
    source_documents,
)
from psycopg.rows import dict_row


def main():
    root = Path(__file__).resolve().parents[1]
    if root.drive.upper() != "D:":
        raise RuntimeError("This integration journey requires the D: workspace")
    run = uuid4().hex
    directory = root / ".finai" / "artifacts" / "guarded-journey" / run
    directory.mkdir(parents=True)
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    operator = Principal(
        actor_id="synthetic-guarded-journey-author",
        display_name="Synthetic integration author",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-journey-" + run,
            period="2026-08",
            currency="XXX",
        ),
        permissions=(
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
            "ingest",
        ),
    )
    reviewer = operator.model_copy(
        update={"actor_id": "synthetic-guarded-journey-reviewer"}
    )
    reader = operator.model_copy(update={"permissions": ("ontology_read",)})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    source_kind, fact_kind, consumer_kind = [
        prefix + run[:12]
        for prefix in ("JourneySource", "JourneyFact", "JourneyConsumer")
    ]
    content = (
        "row_key,date,amount,unit,family\n"
        f"{run}-a,2026-08-01,0.1,FIXTURE_UNITS,SYNTHETIC\n"
        f"{run}-b,2026-08-01,0.2,FIXTURE_UNITS,SYNTHETIC\n"
    ).encode()
    document = source_documents.retain_document(
        operator, "SYNTHETIC-guarded-journey.csv", content
    )
    retained_bytes = source_documents.document_bytes(operator, document["document_id"])[
        1
    ]
    assert retained_bytes == content
    parsed = list(csv.DictReader(io.StringIO(retained_bytes.decode())))

    def item(kind, attrs, *, key=None, evidence="USER_ASSERTED", identity=None):
        return ResourceMutation(
            resource_id=identity or uuid4(),
            object_type=kind,
            identity_key=key or uuid4().hex,
            display_name="SYNTHETIC guarded journey " + kind,
            access_entity="__PLATFORM__"
            if kind == "SchemaDefinition"
            else operator.scope.legal_entity_id,
            attributes=attrs,
            valid_from=start,
            evidence_class=evidence,
        )

    def field(kind, semantic, target=None):
        return {
            "field_id": str(uuid4()),
            "kind": kind,
            "required": True,
            "semantic_id": str(canonical_id(tenant, "SemanticContract", semantic)),
            "target_type": target,
        }

    fields = {
        "row_key": field("identifier", "Identifier"),
        "date": field("date", "Date"),
        "amount": field("decimal", "Amount"),
        "unit": field("identifier", "Identifier"),
        "family": field("identifier", "Identifier"),
        "evidence_id": field("reference", "CanonicalReference", "SourceEvidence"),
        "source_record_id": field("reference", "CanonicalReference", "SourceRecord"),
    }
    source_schema = item(
        "SchemaDefinition",
        {"fields": fields, "additional_fields": False},
        key=source_kind,
    )
    fact_schema = item(
        "SchemaDefinition",
        {"fields": fields, "additional_fields": False},
        key=fact_kind,
    )
    evidence = item(
        "SourceEvidence",
        {"sha256": document["sha256"], "source_system": "SYNTHETIC_G8_INTEGRATION"},
        evidence="SOURCE_BOUND",
        identity=canonical_id(tenant, "SourceEvidence", document["sha256"]),
    )
    inputs = []
    records = []
    for index, row in enumerate(parsed, 2):
        record = item(
            "SourceRecord",
            {
                "evidence_id": str(evidence.resource_id),
                "coordinate": f"CSV!row:{index}",
            },
            evidence="SOURCE_BOUND",
            identity=uuid5(evidence.resource_id, f"CSV!row:{index}"),
        )
        records.append(record)
        inputs.append(
            item(
                source_kind,
                {
                    **row,
                    "evidence_id": str(evidence.resource_id),
                    "source_record_id": str(record.resource_id),
                },
                evidence="SOURCE_BOUND",
            )
        )
    binding = item(
        "ObjectBinding",
        {
            "source_schema_id": str(source_schema.resource_id),
            "target_schema_id": str(fact_schema.resource_id),
            "definition": {
                "identity_field": "row_key",
                "display_field": "row_key",
                "fields": [
                    {"source_field": name, "target_field": name} for name in fields
                ],
            },
        },
    )

    def approve(proposal):
        resources.propose(operator, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Explicit synthetic integration configuration; no authentic finance claim",
            ),
        )

    def publish(items):
        approve(
            ResourceProposal(
                title="SYNTHETIC retained-source integration",
                rationale="Local storage and authority integration only",
                access_entity="__TENANT__",
                mutations=items,
            )
        )

    publish([source_schema, fact_schema, evidence, *records, *inputs, binding])
    prepared = ontology_definitions.prepare_binding(
        operator,
        binding.resource_id,
        ObjectSetQuery(object_type=source_kind),
        "Copy exact synthetic CSV values through the real canonical binding runtime",
    )
    approve(prepared)
    facts = prepared.mutations
    assert len(facts) == 2
    contract = item(
        "FactContract",
        {
            "schema_id": str(fact_schema.resource_id),
            "definition": {
                "grain": ["row_key", "date", "unit"],
                "measure": "amount",
                "aggregation": "flow_sum",
                "time_field": "date",
                "unit_field": "unit",
                "source_family": "SYNTHETIC",
                "source_family_field": "family",
                "authority_basis": "Synthetic source observations only; no financial certification",
            },
        },
    )
    consumer_schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "minimum_authority_state": field("identifier", "Identifier"),
                "contract_id": field("reference", "CanonicalReference", "FactContract"),
                "fact_schema_id": field(
                    "reference", "CanonicalReference", "SchemaDefinition"
                ),
                **{
                    f"fact_{index}": field("reference", "CanonicalReference", fact_kind)
                    for index in range(2)
                },
            },
        },
        key=consumer_kind,
    )
    consumer = item(
        consumer_kind,
        {
            "minimum_authority_state": "OBSERVED",
            "contract_id": str(contract.resource_id),
            "fact_schema_id": str(fact_schema.resource_id),
            **{
                f"fact_{index}": str(fact.resource_id)
                for index, fact in enumerate(facts)
            },
        },
    )
    publish([contract, consumer_schema, consumer])
    head = resources.get_resource(operator, consumer.resource_id)["resource"]
    with (
        resources.resource_connection(operator) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        rows = cursor.execute(
            "SELECT DISTINCT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s",
            (tenant, head["version_id"]),
        ).fetchall()
    pins = [
        VersionReference(
            resource_id=row["target_resource_id"], version_id=row["target_version_id"]
        )
        for row in rows
    ]
    events = {}

    def transition(ref, state):
        request = LifecycleRequest(
            subject=ref,
            expected_event_id=events.get(ref.version_id),
            target_state=state,
            epistemic_state="DERIVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Explicit synthetic integration observation; never financial certification",
        )
        resource_lifecycle.request_transition(operator, request)
        resource_lifecycle.review_transition(
            reviewer,
            request.request_id,
            LifecycleReview(
                decision="APPROVED",
                reason="Independent synthetic integration lifecycle review",
            ),
        )
        events[ref.version_id] = resource_lifecycle.history(operator, ref)["events"][
            -1
        ]["event_id"]

    token = uuid4().hex
    environment = {
        **os.environ,
        "FINAI_ACCESS_TOKENS": json.dumps({token: reader.model_dump(mode="json")}),
    }
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    headers = {"Authorization": f"Bearer {token}"}
    pids = []

    @contextmanager
    def api():
        with (directory / f"api-{len(pids)}.log").open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "finai_api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=root,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            pids.append(process.pid)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Owned API exited; inspect its D: log")
                    try:
                        if (
                            httpx.get(base + "/openapi.json", timeout=1).status_code
                            == 200
                        ):
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Owned API did not become ready")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

    path = f"/v1/ontology/model/facts/{contract.resource_id}/aggregate/guarded"
    request = {
        "consumer": {
            "resource_id": str(consumer.resource_id),
            "version_id": str(head["version_id"]),
        },
        "query": {"object_type": fact_kind},
        "group_by": [],
    }
    with api(), httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        assert client.post(path, json=request).status_code == 409
        for pin in pins:
            transition(pin, "OBSERVED")
        response = client.post(path, json=request)
        assert response.status_code == 200, response.text
        calculated = response.json()
        assert calculated["groups"][0]["value"] == "0.3"
        assert calculated["input_count"] == 2
        assert calculated["financial_certification"] is None
        assert calculated["current_use_authorized"] is False
    with api(), httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        run_path = f"/v1/ontology/model/fact-runs/{calculated['run_id']}"
        assert client.get(run_path).json() == calculated
        assert (
            client.get(run_path + "/authority").json()["status"] == "RECHECK_REQUIRED"
        )
        fact_pin = next(pin for pin in pins if pin.resource_id == facts[0].resource_id)
        transition(fact_pin, "REVOKED")
        assert client.get(run_path + "/authority").json()["status"] == "BLOCKED"
        assert client.post(path, json=request).status_code == 409
        assert client.get(run_path).json() == calculated
    assert (
        source_documents.document_bytes(operator, document["document_id"])[1] == content
    )
    report = {
        "classification": "SYNTHETIC_SOURCE_LOCAL_INTEGRATED_PASS",
        "authentic_source_pass": False,
        "browser_acceptance": False,
        "financial_certification": None,
        "scope": operator.scope.model_dump(mode="json"),
        "source": document,
        "fact_contract_id": str(contract.resource_id),
        "consumer": request["consumer"],
        "run_id": calculated["run_id"],
        "authority_receipt": calculated["authority_check"]["consumption_id"],
        "authority_proof_hash": calculated["authority_check"]["proof_hash"],
        "actual_value": calculated["groups"][0]["value"],
        "expected_value": "0.3",
        "input_count": 2,
        "api_processes": pids,
        "api_restart_reopen": True,
        "withdrawal_refused": True,
        "historical_result_unchanged": True,
        "owned_processes_stopped": True,
    }
    evidence_path = directory / "evidence.json"
    evidence_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(evidence_path), **report}, indent=2))


if __name__ == "__main__":
    main()
