"""Synthetic finance graph with memory storage and real validators.

Pure setup extracted from workspace, metric and source-exception fixtures.
No external files, permission overrides or validator replacements.
"""

import json
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

from test_entity_movement_review import fixture
from test_source_reconciliation_exception import compile_case

from finai_api.domain.authority import ExactScope, canonical_sha256
from finai_api.domain.company_financial_metrics import FinancialMetricRequest
from finai_api.domain.investigation import InvestigationAction
from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Projection, ProjectionRequest
from finai_api.domain.source_reconciliation_exception import SourceExceptionRequest
from finai_api.services import investigation_actions as actions
from finai_api.services import journal_reconciliation
from finai_api.services import ontology_operations as operations
from finai_api.services import source_reconciliation_exception as exceptions
from finai_api.services.entity_movement_review import digest, review
from finai_api.services.posted_movements_function import calculate
from finai_api.services.semantic_analysis_movements import build
from finai_api.services.semantic_analysis_support import pin


def workspace_graph():
    parsed, source, targets, ids = fixture()
    # Synthetic profile only; no retained SEG interpretation is changed.
    targets[ids["scope"]]["attributes"]["source_profile"] = "1c_journal"
    for ref in source["accounts"].values():
        old = targets.pop(ref["resource_id"])
        ref.update(resource_id=str(uuid4()), version_id=str(uuid4()))
        old.update(ref)
        targets[ref["resource_id"]] = old
    targets[ids["company"]] = {"object_type": "LegalEntity", "attributes": {}}
    evidence_id, function_id = str(uuid4()), str(uuid4())
    targets[evidence_id] = {
        "object_type": "SourceEvidence",
        "attributes": {"sha256": source["sha256"]},
    }
    targets[function_id] = {
        "object_type": "FunctionDefinition",
        "attributes": {"definition": {"entity_movement_review": True}},
    }
    targets[ids["scope"]]["object_type"] = "SourceAccountingScope"
    for identity, row in targets.items():
        row.setdefault("resource_id", identity)
        row.setdefault("version_id", str(uuid4()))
        row.setdefault("display_name", row["object_type"])
        row["content_hash"] = digest(row["attributes"])
    for key in ("binding", "scope"):
        source[key] = pin(targets[source[key]["resource_id"]]).model_dump(mode="json")
    source["evidence"] = pin(targets[evidence_id]).model_dump(mode="json")
    source["document_id"] = "ir_" + "1" * 64
    source["entity_movement_review"] = {"policies": {}}
    output = {
        "source_document": source,
        "source_rows": parsed["rows"],
        "source_headers": parsed["headers"],
        "posted_movements": calculate(parsed, source),
        "entity_movement_review": review(parsed, source, targets, {}),
        "run_id": "fcr_" + "2" * 64,
        "authority": "GUARDED_POSTED_MOVEMENT_ANALYSIS",
        "coverage": "RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS",
        "query": {"valid_at": "2026-09-08T00:00:00Z", "known_at": "2026-09-08T00:00:00Z"},
    }
    history = {
        "invocation_id": str(uuid4()),
        "receipt_hash": "3" * 64,
        "receipt": {"recorded_at": "2026-09-08T00:00:01Z"},
        "output": output,
    }
    plan = {
        "source_document": deepcopy(source),
        "function": pin(targets[function_id]).model_dump(mode="json"),
        "static_dependencies": [pin(r).model_dump(mode="json") for r in targets.values()],
        "implementation": {"implementation_id": "accounting.retained-posted-movements/v1"},
    }

    class Resolver:
        def read_session(self):
            return nullcontext(self)

        def version(self, ref):
            return targets[str(ref["resource_id"])]

        def field(self, row, name):
            return targets[row["attributes"][name]]

    return (
        history,
        plan,
        Resolver(),
        ProjectionRequest(invocation_id=history["invocation_id"], company_id=ids["company"]),
    )


def metric_graph(workspace):
    history, plan, resolver, original_request = workspace
    descriptor, projected_rows, _ = build(history, plan, resolver, original_request.company_id)
    projection = Projection(
        descriptor=descriptor,
        descriptor_sha256=digest(
            {
                "descriptor": descriptor.model_dump(mode="json"),
                "rows": [r.model_dump(mode="json") for r in projected_rows],
            }
        ),
        rows=projected_rows,
        total_rows=len(projected_rows),
        sections=[],
        selection=None,
        request=original_request,
    )
    source = history["output"]["source_document"]
    scope = resolver.version(source["scope"])
    ids = {
        **source["context"],
        "legal_entity_id": source["company_id"],
        "chart_id": scope["attributes"]["chart_id"],
    }
    ids["calendar_id"] = resolver.version({"resource_id": ids["ledger_id"]})["attributes"][
        "calendar_id"
    ]
    selected = {
        key: {
            k: str(resolver.version({"resource_id": ids[key]})[k])
            for k in ("resource_id", "version_id")
        }
        for key in (
            "legal_entity_id",
            "ledger_id",
            "book_id",
            "period_id",
            "currency_id",
        )
    }
    selected["calendar_id"] = {"resource_id": ids["calendar_id"], "version_id": str(uuid4())}
    selected["chart_id"] = {"resource_id": ids["chart_id"], "version_id": str(uuid4())}
    review = history["output"]["entity_movement_review"]
    pair = review["pairs"][0]
    entry = {
        "journal": {"resource_id": pair["proposed_entry_id"], "version_id": str(uuid4())},
        "source_coordinate": "Base!S2",
        "lines": [
            {
                "line": {"resource_id": line["proposed_resource_id"], "version_id": str(uuid4())},
                "dimensions": {
                    "state": "COMPLETE",
                    "policy": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
                },
            }
            for line in pair["lines"]
        ],
    }
    receipt = {
        "contract": "source-journal-movement-reconciliation/1",
        "basis": "EXACT_SOURCE_MATCHED_CANONICAL_JOURNALS",
        "selection": selected,
        "snapshot_at": "2026-09-08T00:00:00+00:00",
        "binding": source["binding"],
        "source_sha256": source["sha256"],
        "source_receipt_hash": review["reconciliation"]["receipt_hash"],
        "status": "RECONCILED",
        "accepted": [entry],
        "missing_coordinates": [],
        "excluded_rows": [],
        "rejected": [],
        "movement_trial_balance": review["movements"],
        "matched_source_amount": "731.97",
        "journal_debit_total": "731.97",
        "journal_credit_total": "731.97",
    }
    request = FinancialMetricRequest(
        invocation_id=original_request.invocation_id,
        company_id=original_request.company_id,
        snapshot_at=datetime.fromisoformat(receipt["snapshot_at"]),
    )
    return request, receipt, projection


def exception_context(metric_data, history):
    original, receipt, projection = metric_data
    receipt["receipt_hash"] = digest({k: v for k, v in receipt.items() if k != "receipt_hash"})
    pins = {
        str(p.resource_id): p.model_dump(mode="json")
        for p in [projection.descriptor.company, *projection.descriptor.definitions]
    }
    context = [
        pins.get(ref["resource_id"], {**ref, "content_hash": "b" * 64})
        for ref in receipt["selection"].values()
    ]
    request = SourceExceptionRequest(
        company_id=original.company_id,
        invocation_id=original.invocation_id,
        journal_snapshot_at=original.snapshot_at,
        expected_reconciliation_receipt_hash=receipt["receipt_hash"],
        coordinate="Base!S2",
    )
    principal = Principal(
        actor_id="test",
        display_name="Test",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id=str(original.company_id),
            period="2025-01",
            currency="GEL",
        ),
    )
    return principal, request, receipt, projection, history, context


def source_graph():
    workspace = workspace_graph()
    history, source_plan, source_resolver, _ = workspace
    p, req, receipt, projection, history, context = exception_context(
        metric_graph(workspace), history
    )
    p = p.model_copy(update={"permissions": ("ontology_read", "ontology_propose")})
    source = history["output"]["source_document"]
    targets = {
        ref["resource_id"]: source_resolver.version(ref)
        for ref in source_plan["static_dependencies"]
    }
    review = history["output"]["entity_movement_review"]
    pair = review["pairs"][0]
    entry = {
        "resource_id": pair["proposed_entry_id"],
        "version_id": str(uuid4()),
        "authority_state": "APPROVED",
        "valid_from": "2025-01-01",
        "valid_to": None,
        "attributes": deepcopy(pair["entry"]),
    }
    lines = []
    for original in pair["lines"]:
        account = targets[original["account"]["resource_id"]]
        lines.append(
            {
                "line": {
                    "resource_id": original["proposed_resource_id"],
                    "version_id": str(uuid4()),
                    "authority_state": "APPROVED",
                    "valid_from": entry["valid_from"],
                    "valid_to": None,
                    "attributes": {
                        "side": original["side"],
                        "amount": original["amount"],
                        "account_id": account["resource_id"],
                        "journal_id": entry["resource_id"],
                        "accounting_binding_id": source["binding"]["resource_id"],
                    },
                },
                "account": account,
                "source_record": {
                    "attributes": {
                        "coordinate": pair["source_coordinate"],
                        "evidence_id": source["evidence"]["resource_id"],
                    }
                },
                "dimensions": {
                    "state": "COMPLETE",
                    "policy": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
                },
            }
        )
    new_req = req.model_copy(
        update={"journal_snapshot_at": req.journal_snapshot_at + timedelta(hours=1)}
    )
    detail = {
        "journal": entry,
        "binding": targets[source["binding"]["resource_id"]],
        "lines": lines,
        "integrity": {"issues": []},
        "selection": receipt["selection"],
        "snapshot_at": new_req.journal_snapshot_at.isoformat(),
    }
    old_receipt = journal_reconciliation.compile_reconciliation(
        review, source, targets, [], receipt["selection"], req.journal_snapshot_at.isoformat()
    )
    new_receipt = journal_reconciliation.compile_reconciliation(
        review,
        source,
        targets,
        [detail],
        receipt["selection"],
        new_req.journal_snapshot_at.isoformat(),
    )
    assert old_receipt["status"] == "UNAVAILABLE", old_receipt
    assert new_receipt["status"] == "RECONCILED", new_receipt
    old_req = req.model_copy(
        update={"expected_reconciliation_receipt_hash": old_receipt["receipt_hash"]}
    )
    new_req = new_req.model_copy(
        update={"expected_reconciliation_receipt_hash": new_receipt["receipt_hash"]}
    )
    old = compile_case((p, old_req, old_receipt, projection, history, context))
    new = compile_case((p, new_req, new_receipt, projection, history, context))

    def retained(value):
        payload = {
            **value.model_dump(mode="json"),
            "scope": p.scope.model_dump(mode="json"),
            "calculation_runtime": "source-reconciliation-exceptions/1",
            "read_permissions": sorted(p.permissions),
        }
        payload["run_id"] = (
            "fcr_"
            + sha256(
                json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
        )
        return payload

    old_run, new_run = retained(old), retained(new)
    open_request = InvestigationAction(
        request_id=uuid4(),
        exception_run_id=old_run["run_id"],
        rationale="Offline synthetic contract fixture: inspect source exception",
    )
    opened = actions.proposal_for(p, open_request, old)

    def freeze(proposal):
        identity = "opa_" + operations.digest(
            [
                p.scope.model_dump(mode="json"),
                "CANONICAL_RESOURCE_PROPOSAL",
                operations.proposal_effect(proposal),
            ]
        )
        return identity, proposal.model_copy(
            update={"proposal_id": uuid5(p.scope.tenant_id, identity)}
        )

    _open_id, opened = freeze(opened)

    def versions(proposal):
        return [
            {
                **m.model_dump(mode="json", exclude={"expected_version_id"}),
                "proposal_id": str(proposal.proposal_id),
                "version_id": str(uuid5(proposal.proposal_id, str(m.resource_id))),
                "content_hash": canonical_sha256(m),
                "valid_from": m.valid_from,
            }
            for m in proposal.mutations
        ]

    open_versions = versions(opened)

    return {
        "p": p,
        "opened": opened,
        "old_run": old_run,
        "new_run": new_run,
        "targets": targets,
        "source": source,
        "entry": entry,
        "lines": lines,
        "open_versions": open_versions,
        "context": context,
        "new_receipt": new_receipt,
    }


def full_graph():
    ns = source_graph()
    principal = ns["p"]
    opened = ns["opened"]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rows = {}
    edges = []
    runs = {ns["old_run"]["run_id"]: ns["old_run"], ns["new_run"]["run_id"]: ns["new_run"]}

    def add(row):
        row = deepcopy(row)
        row.setdefault("resource_id", str(uuid4()))
        row.setdefault("version_id", str(uuid4()))
        row.setdefault("authority_state", "APPROVED")
        row.setdefault(
            "evidence_class",
            "SOURCE_BOUND"
            if row["object_type"] in ("SourceEvidence", "SourceAccountingScope")
            else "USER_ASSERTED",
        )
        row.setdefault("access_entity", principal.scope.legal_entity_id)
        row.setdefault("identity_key", "fixture:" + row["resource_id"])
        row.setdefault("display_name", "SYNTHETIC " + row["object_type"])
        row.setdefault("schema_version_id", None)
        row.setdefault("content_hash", exceptions.digest(json.loads(json.dumps(row, default=str))))
        row.setdefault("proposal_id", str(uuid4()))
        row.setdefault("valid_from", now)
        row.setdefault("valid_to", None)
        row.setdefault("system_from", now)
        if isinstance(row["valid_from"], str):
            row["valid_from"] = datetime.fromisoformat(row["valid_from"]).replace(tzinfo=UTC)
        for key in ("resource_id", "version_id", "proposal_id"):
            row[key] = UUID(str(row[key]))
        rows[str(row["resource_id"])] = row
        return row

    for row in ns["targets"].values():
        add(row)
    rows[ns["source"]["scope"]["resource_id"]]["attributes"]["evidence_id"] = ns["source"][
        "evidence"
    ]["resource_id"]
    for field, kind in [
        ("legal_entity_id", "LegalEntity"),
        ("chart_id", "LocalChartOfAccounts"),
        ("calendar_id", "FiscalCalendar"),
    ]:
        ref = ns["new_receipt"]["selection"][field]
        if ref["resource_id"] not in rows:
            attrs = (
                {"legal_entity_id": principal.scope.legal_entity_id} if field == "chart_id" else {}
            )
            add(
                {
                    **ref,
                    "content_hash": next(
                        p["content_hash"]
                        for p in ns["context"]
                        if p["resource_id"] == ref["resource_id"]
                    ),
                    "object_type": kind,
                    "attributes": attrs,
                }
            )
    entry = add({**ns["entry"], "object_type": "JournalEntry"})
    record = add(
        {
            "object_type": "SourceRecord",
            "attributes": {
                "evidence_id": ns["source"]["evidence"]["resource_id"],
                "coordinate": "Base!S2",
            },
            "evidence_class": "SOURCE_BOUND",
        }
    )
    for line in ns["lines"]:
        policy = add(
            {
                **line["dimensions"]["policy"],
                "object_type": "AccountDimensionPolicy",
                "attributes": {
                    "account_id": line["account"]["resource_id"],
                    "definition": {
                        "contract": "account-dimension-policy/1",
                        "reason": "Explicit synthetic no additional dimension rules",
                        "rules": [],
                    },
                },
            }
        )
        item = deepcopy(line["line"])
        item["object_type"] = "JournalLine"
        item["attributes"].update(
            source_record_id=str(record["resource_id"]),
            dimension_policy_id=str(policy["resource_id"]),
            dimensions={
                "contract": "journal-line-dimensions/1",
                "policy": {k: str(policy[k]) for k in ("resource_id", "version_id")},
                "assignments": [],
            },
        )
        add(item)
    # Real platform schemas, no permissive substitutes.
    for definition in platform_definitions(principal.scope.tenant_id):
        rid = canonical_id(
            principal.scope.tenant_id, definition["object_type"], definition["identity_key"]
        )
        add(
            {
                **definition,
                "resource_id": str(rid),
                "version_id": str(uuid5(rid, "synthetic-schema-version")),
                "access_entity": "__PLATFORM__",
            }
        )
    for row in ns["open_versions"]:
        add(row)
    # Exact FIELD dependencies for the complete fixture graph, plus source journal context.
    for row in list(rows.values()):
        for field, value in row["attributes"].items():
            if isinstance(value, str) and value in rows:
                target = rows[value]
                edges.append(
                    {
                        "version_id": row["version_id"],
                        "target_resource_id": target["resource_id"],
                        "target_version_id": target["version_id"],
                        "relation": "FIELD:" + field,
                    }
                )

    # Lines retain source-record and parent references; headers retain the binding.
    def response(one=None, many=None):
        return SimpleNamespace(fetchone=lambda: one, fetchall=lambda: many or [])

    queries = []
    proposals = {}
    decisions = {}
    snapshots = {}
    pending_versions = {}
    versions_by_id = {str(r["version_id"]): r for r in rows.values()}

    class Memory:
        @contextmanager
        def cursor(self, **kwargs):
            yield self

        def execute(self, sql, args):
            queries.append(sql)
            if sql.startswith("SELECT request_hash FROM resource_proposals"):
                row = proposals.get(str(args[1]))
                return response(one=(row["request_hash"],) if row else None)
            if sql.startswith("INSERT INTO resource_proposals"):
                proposals[str(args[1])] = {
                    "tenant_id": args[0],
                    "proposal_id": args[1],
                    "access_entity": args[2],
                    "submitted_by": args[3],
                    "title": args[4],
                    "rationale": args[5],
                    "request_hash": args[6],
                    "payload": deepcopy(args[7].obj),
                    "created_at": now,
                }
                return response()
            if sql.startswith("INSERT INTO proposal_impact_snapshots"):
                snapshots[str(args[1])] = {
                    "snapshot": deepcopy(args[3].obj),
                    "fingerprint": args[4],
                }
                return response()
            if sql.startswith("SELECT snapshot,fingerprint FROM proposal_impact_snapshots"):
                return response(one=snapshots.get(str(args[1])))
            if sql.startswith("SELECT p.*") or sql.startswith("SELECT * FROM resource_proposals"):
                row = proposals.get(str(args[1]))
                decision = decisions.get(str(args[1]), {})
                return response(
                    one={
                        **row,
                        "decision": decision.get("decision"),
                        "reviewed_by": decision.get("reviewed_by"),
                        "review_rationale": decision.get("rationale"),
                        "recorded_at": decision.get("recorded_at"),
                    }
                    if row
                    else None
                )
            if sql.startswith("SELECT * FROM resource_decisions"):
                return response(one=decisions.get(str(args[1])))
            if sql.startswith("INSERT INTO resource_decisions"):
                decisions[str(args[1])] = {
                    "decision": args[3],
                    "reviewed_by": args[4],
                    "rationale": args[5],
                    "recorded_at": now,
                }
                return response()
            if sql.startswith("INSERT INTO canonical_identities"):
                return response()
            if sql.startswith("INSERT INTO resource_versions"):
                fields = (
                    "tenant_id",
                    "resource_id",
                    "version_id",
                    "access_entity",
                    "object_type",
                    "display_name",
                    "schema_version_id",
                    "attributes",
                    "content_hash",
                    "valid_from",
                    "valid_to",
                    "authority_state",
                    "evidence_class",
                    "proposal_id",
                )
                row = dict(zip(fields, args, strict=True))
                row["attributes"] = deepcopy(args[7].obj)
                row["system_from"] = now
                row["identity_key"] = rows[str(row["resource_id"])]["identity_key"]
                pending_versions[str(row["version_id"])] = row
                versions_by_id[str(row["version_id"])] = row
                return response()
            if sql.startswith("INSERT INTO resource_heads"):
                rows[str(args[1])] = pending_versions[str(args[2])]
                return response()
            if sql.startswith("INSERT INTO resource_dependencies"):
                edges.append(
                    {
                        "version_id": UUID(str(args[1])),
                        "target_resource_id": UUID(str(args[2])),
                        "target_version_id": UUID(str(args[3])),
                        "relation": args[4],
                    }
                )
                return response()
            if "pg_advisory" in sql or "set_config" in sql:
                return response()
            if "IN ('SchemaDefinition','LinkType')" in sql:
                return response(
                    many=[
                        r
                        for r in rows.values()
                        if r["object_type"] in ("SchemaDefinition", "LinkType")
                    ]
                )
            if "v.object_type='IdentityResolution'" in sql or "object_type='ObjectBinding'" in sql:
                return response(many=[])
            if sql.startswith("SELECT 1 FROM resource_heads"):
                return response(one=(1,) if str(args[1]) in rows else None)
            if "g8_has_hidden_current_dependents" in sql:
                return response(one=(False,))
            if "bool_or(" in sql:
                found = []
                for e in edges:
                    if e["target_resource_id"] == args[1]:
                        row = versions_by_id[str(e["version_id"])]
                        if rows[str(row["resource_id"])] != row:
                            continue
                        found.append(
                            {
                                k: row[k]
                                for k in (
                                    "resource_id",
                                    "version_id",
                                    "object_type",
                                    "display_name",
                                    "access_entity",
                                )
                            }
                        )
                        found[-1]["cycle_dependency"] = not e["relation"].startswith(
                            ("BOUND_SOURCE:", "CALCULATED_BINDING:")
                        )
                return response(many=found)
            if "FROM resource_dependencies" in sql:
                if "version_id=ANY" in sql:
                    found = [e for e in edges if e["version_id"] in args[1]]
                elif "version_id=%s" in sql:
                    found = [e for e in edges if e["version_id"] == args[1]]
                else:
                    raise AssertionError("Unhandled dependency query " + sql)
                return response(many=found)
            if "FROM resource_lifecycle_events" in sql:
                return response(
                    one={
                        "event_id": uuid5(args[1], "available"),
                        "payload": {"target_state": "OBSERVED", "availability_state": "AVAILABLE"},
                        "certification_proof_hash": None,
                    }
                )
            if "version_id=ANY" in sql and "FROM resource_versions" in sql:
                return response(many=[r for r in rows.values() if r["version_id"] in args[1]])
            if "g8_effective_version_id" in sql:
                row = rows.get(str(args[2]))
                return response(
                    one={**row, "effective_version_id": row["version_id"]}
                    if row and row["version_id"] == args[3]
                    else None
                )
            if "h.resource_id=%s" in sql:
                return response(one=rows.get(str(args[1])))
            if (
                "FROM resource_versions" in sql
                and "resource_id=%s" in sql
                and "version_id=%s" in sql
            ):
                row = rows.get(str(args[1]))
                return response(one=row if row and row["version_id"] == args[2] else None)
            raise AssertionError("UNHANDLED_SQL: " + sql)

    conn = Memory()

    @contextmanager
    def memory_connection(*a, **k):
        yield conn

    return SimpleNamespace(
        principal=principal,
        opened=opened,
        rows=rows,
        edges=edges,
        runs=runs,
        entry=entry,
        decisions=decisions,
        connection=memory_connection,
        conn=conn,
        ns=ns,
    )
