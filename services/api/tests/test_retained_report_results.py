"""Retained report composition: real projection and authority guards, synthetic reads."""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from investigation_full_review_support import workspace_graph

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import ProjectionRequest
from finai_api.services import retained_report_results as service
from finai_api.services import semantic_analysis
from finai_api.services.semantic_analysis_support import digest, pin
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def graph(monkeypatch):
    history, plan, resolver, request = workspace_graph()
    principal = Principal(
        actor_id="report-reader",
        display_name="Report reader",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id=str(request.company_id),
            period="2025-01",
            currency="GEL",
        ),
    )
    records = {r["resource_id"]: resolver.version(r) for r in plan["static_dependencies"]}
    for row in records.values():
        row.update(
            authority_state="APPROVED",
            access_entity=str(request.company_id),
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=None,
        )
    events, dependencies = {}, {}

    class Memory:
        @contextmanager
        def cursor(self, **kwargs):
            yield self

        def execute(self, sql, args=()):
            one, many = None, []
            if "pg_advisory" in sql:
                pass
            elif "g8_effective_version_id" in sql:
                row = records.get(str(args[2]))
                if row and str(row["version_id"]) == str(args[3]):
                    one = {**row, "effective_version_id": UUID(row["version_id"])}
            elif "FROM resource_lifecycle_events" in sql:
                one = events.get(str(args[1]))
            elif "FROM resource_dependencies" in sql:
                many = dependencies.get(str(args[1]), [])
            else:
                raise AssertionError(sql)
            return SimpleNamespace(fetchone=lambda: one, fetchall=lambda: many)

    @contextmanager
    def connection(*args, **kwargs):
        yield Memory()

    def load(p, invocation_id):
        assert p == principal
        if str(invocation_id) != history["invocation_id"]:
            raise WorkspaceError(404, "Invocation unavailable")
        return history, plan, resolver

    context = {
        "company_directory": {"companies": [{"company": {"resource_id": str(request.company_id)}}]}
    }
    monkeypatch.setattr(semantic_analysis, "load", load)
    monkeypatch.setattr(service, "resource_connection", connection)
    monkeypatch.setattr(service.company_context, "resolve", lambda *args: context)
    projected = semantic_analysis.project(principal, request)
    section_data = dict(
        section_id=uuid4(),
        title="Retained movements",
        invocation_id=request.invocation_id,
        receipt_hash=history["receipt_hash"],
        descriptor_sha256=projected.descriptor_sha256,
        columns=["account", "debit_movement"],
        filters=[],
        group_by=None,
    )

    def section(**updates):
        # The shared domain model is owned by the integration lane.
        from finai_api.domain.retained_reports import ReportSectionReference

        return ReportSectionReference(**{**section_data, **updates})

    return SimpleNamespace(
        principal=principal,
        company=request.company_id,
        history=history,
        plan=plan,
        resolver=resolver,
        records=records,
        events=events,
        dependencies=dependencies,
        context=context,
        projection=projected,
        section=section,
        connection=connection,
    )


def test_full_rows_exact_evidence_and_independent_clocks_without_execution(graph, monkeypatch):
    from finai_api.services import company_financial_metrics, function_invocations

    def forbidden(*args, **kwargs):
        raise AssertionError("Report composition must not execute financial work")

    monkeypatch.setattr(function_invocations, "invoke", forbidden)
    monkeypatch.setattr(company_financial_metrics, "produce", forbidden)
    before = deepcopy(graph.history)
    result = service.resolve(graph.principal, graph.company, [graph.section()])[0]
    expected = graph.projection.model_dump(mode="json")
    expected["request"]["descriptor_sha256"] = graph.projection.descriptor_sha256
    assert result["projection"] == expected
    assert len(result["projection"]["rows"]) == len(result["contributors"]) == 2
    assert {c["coordinate"] for cells in result["contributors"].values() for c in cells} == {
        "Base!S2"
    }
    assert result["reference"]["columns"] == ["account", "debit_movement"]
    assert result["authority_observation"]["roots"]
    assert "checked_at" not in result["authority_observation"]
    assert result["current_use_authorized"] is False
    assert graph.history == before


def test_filtered_view_preserves_full_result_count_and_exact_selected_evidence(graph):
    field = next(f for f in graph.projection.descriptor.fields if f.key == "account")
    section = graph.section(
        filters=[{"field": "account", "value": field.options[0].value}], group_by="account"
    )
    result = service.resolve(graph.principal, graph.company, [section])[0]
    assert result["projection"]["total_rows"] == 2
    assert len(result["projection"]["rows"]) == len(result["contributors"]) == 1
    assert result["projection"]["sections"][0]["row_keys"] == list(result["contributors"])


@pytest.mark.parametrize(
    "change,status",
    [
        ("receipt", 409),
        ("revision", 409),
        ("columns", 422),
        ("company", 404),
        ("unestablished", 404),
        ("unsupported", 422),
        ("withdrawn", 409),
        ("denied", 404),
        ("currency", 409),
        ("clock", 409),
    ],
)
def test_invalid_new_report_is_refused(graph, change, status):
    section, company = graph.section(), graph.company
    if change == "receipt":
        section = graph.section(receipt_hash="f" * 64)
    elif change == "revision":
        section = graph.section(descriptor_sha256="f" * 64)
    elif change == "columns":
        section = graph.section(columns=["invented"])
    elif change == "company":
        company = uuid4()
    elif change == "unestablished":
        graph.context["company_directory"]["companies"] = []
    elif change == "unsupported":
        graph.plan["implementation"]["implementation_id"] = "unknown/v1"
    elif change == "withdrawn":
        graph.events[graph.plan["function"]["version_id"]] = {
            "payload": {"target_state": "REVOKED", "availability_state": "AVAILABLE"}
        }
    elif change == "denied":
        graph.records.pop(graph.plan["function"]["resource_id"])
    elif change == "currency":
        currency_id = graph.plan["source_document"]["context"]["currency_id"]
        graph.records[currency_id]["object_type"] = "LocalAccount"
    elif change == "clock":
        graph.history["output"]["query"]["valid_at"] = "2025-01-01"
    with pytest.raises(WorkspaceError) as error:
        service.resolve(graph.principal, company, [section])
    assert error.value.status == status


def test_indirect_withdrawal_is_checked_by_shared_upstream_guard(graph):
    root = graph.plan["function"]
    dependent = next(r for r in graph.records.values() if r["object_type"] == "LocalAccount")
    graph.dependencies[root["version_id"]] = [
        {
            "target_resource_id": UUID(dependent["resource_id"]),
            "target_version_id": UUID(dependent["version_id"]),
            "relation": "INPUT",
        }
    ]
    graph.events[dependent["version_id"]] = {
        "payload": {"target_state": "REVOKED", "availability_state": "AVAILABLE"}
    }
    with pytest.raises(WorkspaceError, match="Upstream dependency"):
        service.authority(graph.principal, [pin(graph.records[root["resource_id"]])])


def test_section_count_and_scope_permission_boundaries(graph):
    with pytest.raises(WorkspaceError) as error:
        service.resolve(graph.principal, graph.company, [graph.section()] * 9)
    assert error.value.status == 422
    with pytest.raises(WorkspaceError):
        service.resolve(graph.principal, graph.company, [])
    with pytest.raises(HTTPException) as error:
        service.resolve(
            graph.principal.model_copy(update={"permissions": ()}), graph.company, [graph.section()]
        )
    assert error.value.status_code == 403


def test_historical_projection_survives_withdrawal_but_new_save_does_not(graph):
    section = graph.section()
    saved = service.resolve(graph.principal, graph.company, [section])[0]
    graph.events[graph.plan["function"]["version_id"]] = {
        "payload": {"target_state": "REVOKED", "availability_state": "AVAILABLE"}
    }
    retained = semantic_analysis.project(
        graph.principal,
        ProjectionRequest(
            invocation_id=section.invocation_id,
            company_id=graph.company,
            descriptor_sha256=section.descriptor_sha256,
        ),
    )
    assert retained.model_dump(mode="json") == saved["projection"]
    with pytest.raises(WorkspaceError):
        service.resolve(graph.principal, graph.company, [section])


def test_accepted_section_checks_source_and_exact_journal_line_policy_roots(graph, monkeypatch):
    from finai_api.domain.retained_reports import ReportSectionReference
    from test_semantic_analysis_accepted_movements import case

    from finai_api.services import company_financial_metrics, journal_reconciliation

    history, plan, resolver, company, *_ = case.__wrapped__()
    principal = graph.principal.model_copy(
        update={"scope": graph.principal.scope.model_copy(update={"legal_entity_id": str(company)})}
    )
    resolver.principal = principal
    resolver.read_session = nullcontext
    plan["implementation"] = history["output"]["implementation"]
    plan["static_dependencies"] = plan["accepted_movements"]["contributors"]

    def load(p, identity):
        assert p == principal
        if str(identity) == history["invocation_id"]:
            return history, plan, resolver
        if str(identity) == resolver.source_history["invocation_id"]:
            return resolver.source_history, resolver.source_plan, resolver.source_resolver
        raise WorkspaceError(404, "Unknown invocation")

    def forbidden(*args, **kwargs):
        raise AssertionError("Report must not rerun the financial producer")

    monkeypatch.setattr(semantic_analysis, "load", load)
    monkeypatch.setattr(company_financial_metrics, "produce", forbidden)
    monkeypatch.setattr(journal_reconciliation, "reconcile", forbidden)
    graph.context["company_directory"]["companies"][0]["company"]["resource_id"] = str(company)
    refs = [
        plan["function"],
        *plan["static_dependencies"],
        resolver.source_plan["function"],
        *resolver.source_plan["static_dependencies"],
    ]
    for journal in history["output"]["financial_metrics"]["journals"]:
        refs.extend([*journal["lines"], *journal["dimension_policies"]])
    for ref in refs:
        row = resolver.version(ref)
        graph.records[str(row["resource_id"])] = {
            **row,
            "authority_state": "APPROVED",
            "access_entity": str(company),
            "valid_from": datetime(2025, 1, 1, tzinfo=UTC),
            "valid_to": None,
        }
    projection = semantic_analysis.project(
        principal, ProjectionRequest(invocation_id=history["invocation_id"], company_id=company)
    )
    section = ReportSectionReference(
        section_id=uuid4(),
        title="Accepted movements",
        invocation_id=history["invocation_id"],
        receipt_hash=history["receipt_hash"],
        descriptor_sha256=projection.descriptor_sha256,
        columns=["account", "credit_movement"],
    )
    result = service.resolve(principal, company, [section])[0]
    roots = result["authority_observation"]["roots"]
    assert resolver.source_plan["function"] in roots
    for journal in history["output"]["financial_metrics"]["journals"]:
        for ref in [journal["journal"], *journal["lines"], *journal["dimension_policies"]]:
            assert any(all(r[k] == v for k, v in ref.items()) for r in roots)
    assert len(result["contributors"]) == 2


@pytest.mark.parametrize("count", [120, 1001])
def test_complete_projection_is_never_truncated_to_a_ui_page(graph, monkeypatch, count):
    from finai_api.domain.semantic_analysis import Value
    from finai_api.services import semantic_analysis_movements

    original = semantic_analysis_movements.build

    def large_projection(*args):
        descriptor, rows, contributors = original(*args)
        # Projection-boundary fixture: no claim that these added rows are source postings.
        template = rows[0]
        expanded = [
            template.model_copy(update={"key": "row_" + digest(index)}) for index in range(count)
        ]
        expanded[0] = expanded[0].model_copy(
            update={
                "values": {
                    **expanded[0].values,
                    "debit_movement": Value(state="MISSING"),
                    "credit_movement": Value(state="NULL"),
                }
            }
        )
        descriptor = descriptor.model_copy(
            update={"excluded_evidence": [contributors[template.key][0]]}
        )
        return descriptor, expanded, {row.key: contributors[template.key] for row in expanded}

    monkeypatch.setattr(semantic_analysis_movements, "build", large_projection)
    descriptor, rows, _ = large_projection(graph.history, graph.plan, graph.resolver, graph.company)
    revision = digest(
        {
            "descriptor": descriptor.model_dump(mode="json"),
            "rows": [row.model_dump(mode="json") for row in rows],
        }
    )
    section = graph.section(descriptor_sha256=revision)
    if count > 1000:
        with pytest.raises(WorkspaceError, match="bound"):
            service.resolve(graph.principal, graph.company, [section])
        return
    result = service.resolve(graph.principal, graph.company, [section])[0]
    assert len(result["projection"]["rows"]) == len(result["contributors"]) == count
    assert result["projection"]["rows"][0]["values"]["debit_movement"]["state"] == "MISSING"
    assert result["projection"]["rows"][0]["values"]["credit_movement"]["state"] == "NULL"
    assert result["projection"]["descriptor"]["excluded_evidence"]
