"""Retain exact Metric observations using existing Function evidence and fact-run storage."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from pydantic import ValidationError

from finai_api.domain.metric_execution import (
    CurrencyUnit,
    DefinitionSnapshot,
    MetricDefinition,
    MetricOutput,
    ObjectCount,
    ObserveRequest,
    Pin,
)
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.security import require_permission
from finai_api.services import fact_runs, function_invocations, resources
from finai_api.services.certification import _current
from finai_api.services.workspace import WorkspaceError

RUNTIME = "metric-observations/1"


def discover(
    principal,
    after_resource_id: UUID | None = None,
    *,
    function_resource_id: UUID | None = None,
    function_version_id: UUID | None = None,
    function_content_hash: str | None = None,
):
    """Bounded canonical catalog; cursor advances over candidates even when none qualify."""
    require_permission(principal, "ontology_read")
    parts = (function_resource_id, function_version_id, function_content_hash)
    if any(part is not None for part in parts) and not all(part is not None for part in parts):
        raise WorkspaceError(422, "Function filter requires resource, version and content hash")
    try:
        selected = (
            Pin(resource_id=parts[0], version_id=parts[1], content_hash=parts[2])
            if parts[0] is not None
            else None
        )
    except ValidationError as exc:
        raise WorkspaceError(422, "Invalid exact Function filter") from exc
    now = datetime.now(UTC)
    snapshot = DefinitionSnapshot(valid_at=now, known_at=now)
    with (
        resources.resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        rows = cur.execute(
            "SELECT v.* FROM resource_versions v WHERE v.tenant_id=%s "
            "AND v.access_entity IN (%s,'__TENANT__','__PLATFORM__') "
            "AND v.object_type='MetricDefinition' AND v.authority_state='APPROVED' "
            "AND v.evidence_class<>'REFERENCE_TEMPLATE' "
            "AND v.version_id=g8_effective_version_id(v.tenant_id,v.resource_id,%s) "
            "AND v.attributes ? 'function_id' AND v.attributes ? 'definition' "
            "AND (v.attributes->>'legal_entity_id' IS NULL "
            "OR v.attributes->>'legal_entity_id'=%s) "
            "AND (%s::uuid IS NULL OR v.resource_id>%s) "
            "AND (%s::uuid IS NULL OR EXISTS (SELECT 1 FROM resource_dependencies d "
            "JOIN resource_versions f ON f.tenant_id=d.tenant_id "
            "AND f.resource_id=d.target_resource_id AND f.version_id=d.target_version_id "
            "WHERE d.tenant_id=v.tenant_id AND d.version_id=v.version_id "
            "AND d.relation='FIELD:function_id' AND f.resource_id=%s "
            "AND f.version_id=%s AND f.content_hash=%s)) "
            "ORDER BY v.resource_id LIMIT 51",
            (
                principal.scope.tenant_id,
                principal.scope.legal_entity_id,
                now,
                principal.scope.legal_entity_id,
                after_resource_id,
                after_resource_id,
                function_resource_id,
                function_resource_id,
                function_version_id,
                function_content_hash,
            ),
        ).fetchall()
        page = rows[:50]
        items = []
        for row in page:
            row["dependencies"] = cur.execute(
                "SELECT d.relation,v.* FROM resource_dependencies d JOIN resource_versions v "
                "ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id "
                "AND v.version_id=d.target_version_id "
                "WHERE d.tenant_id=%s AND d.version_id=%s LIMIT 101",
                (principal.scope.tenant_id, row["version_id"]),
            ).fetchall()
            try:
                _current(
                    cur,
                    principal,
                    VersionReference(resource_id=row["resource_id"], version_id=row["version_id"]),
                )
                item = catalog_item(principal, row, snapshot)
            except WorkspaceError as exc:
                if exc.status not in (404, 409):
                    raise
                continue
            except (ValueError, KeyError, TypeError):
                continue
            if selected is None or Pin.model_validate(item["function"]) == selected:
                items.append(item)
    return {
        "contract": "metric-catalog/1",
        "items": items,
        "next_cursor": str(page[-1]["resource_id"]) if len(rows) > 50 else None,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def catalog_item(principal, row, snapshot):
    if (
        row["object_type"] != "MetricDefinition"
        or row["authority_state"] != "APPROVED"
        or row.get("evidence_class") == "REFERENCE_TEMPLATE"
        or len(row["dependencies"]) > 100
    ):
        raise ValueError("Accepted executable Metric unavailable")
    validate_snapshot(row, snapshot)
    attrs = row["attributes"]
    spec = MetricDefinition.model_validate(attrs["definition"])
    function = pin(dependency(row, "FIELD:function_id", attrs["function_id"], "FunctionDefinition"))
    company = (
        pin(dependency(row, "FIELD:legal_entity_id", attrs["legal_entity_id"], "LegalEntity"))
        if attrs.get("legal_entity_id")
        else None
    )
    if company and str(company.resource_id) != principal.scope.legal_entity_id:
        raise ValueError("Metric company differs from selected scope")
    if isinstance(spec.selector, ObjectCount) and bool(company) != bool(
        spec.selector.company_field
    ):
        raise ValueError("Company count requires an explicit query field")
    if isinstance(spec.unit, CurrencyUnit) and (
        pin(dependency(row, "METRIC_UNIT", spec.unit.reference.resource_id, "Currency"))
        != spec.unit.reference
    ):
        raise ValueError("Metric currency pin differs")
    return {
        "metric": pin(row).model_dump(mode="json"),
        "display_name": row["display_name"],
        "function": function.model_dump(mode="json"),
        "company": company.model_dump(mode="json") if company else None,
        "definition": spec.model_dump(mode="json"),
        "definition_snapshot": snapshot.model_dump(mode="json"),
        "definition_temporal": {
            "system_from": timestamp(row["system_from"]).isoformat(),
            "valid_from": timestamp(row["valid_from"]).isoformat(),
            "valid_to": timestamp(row["valid_to"]).isoformat() if row.get("valid_to") else None,
        },
    }


def pin(row):
    return Pin.model_validate({k: row[k] for k in ("resource_id", "version_id", "content_hash")})


def validate_publication(item, target):
    attrs = item.attributes
    if not ({"function_id", "definition"} & attrs.keys()):
        if "legal_entity_id" in attrs:
            raise WorkspaceError(422, "Legacy MetricDefinition cannot declare execution scope")
        return  # Minimal legacy definitions stay non-executable.
    if not {"function_id", "definition"} <= attrs.keys():
        raise WorkspaceError(422, "Executable Metric requires function_id and definition together")
    try:
        spec = MetricDefinition.model_validate(attrs["definition"])
        function = target(str(attrs["function_id"]), str(item.resource_id), "METRIC_FUNCTION")
        if function["object_type"] != "FunctionDefinition":
            raise ValueError("Metric target must be a FunctionDefinition")
        if isinstance(spec.selector, ObjectCount):
            if (
                function["attributes"]["definition"]["implementation_id"]
                != "ontology.object-set-derived/v1"
            ):
                raise ValueError("Object count requires the shared ontology Function")
            if bool(attrs.get("legal_entity_id")) != bool(spec.selector.company_field):
                raise ValueError("Company count requires explicit company and query field together")
        if isinstance(spec.unit, CurrencyUnit):
            unit = target(
                str(spec.unit.reference.resource_id), str(item.resource_id), "METRIC_UNIT"
            )
            if unit["object_type"] != "Currency" or pin(unit) != spec.unit.reference:
                raise ValueError("Metric currency requires an exact Currency pin")
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(422, "Invalid executable Metric definition") from exc


def definition(principal, expected):
    with (
        resources.resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        row = cur.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v JOIN canonical_identities i "
            "USING(tenant_id,resource_id) WHERE v.tenant_id=%s "
            "AND v.resource_id=%s AND v.version_id=%s",
            (principal.scope.tenant_id, expected.resource_id, expected.version_id),
        ).fetchone()
        if (
            not row
            or pin(row) != expected
            or row["object_type"] != "MetricDefinition"
            or row["authority_state"] != "APPROVED"
            or row["evidence_class"] == "REFERENCE_TEMPLATE"
        ):
            raise WorkspaceError(404, "Exact accepted Metric definition unavailable")
        row["dependencies"] = cur.execute(
            "SELECT d.relation,v.* FROM resource_dependencies d JOIN resource_versions v "
            "ON v.tenant_id=d.tenant_id AND v.version_id=d.target_version_id "
            "AND v.resource_id=d.target_resource_id "
            "WHERE d.tenant_id=%s AND d.version_id=%s LIMIT 101",
            (principal.scope.tenant_id, expected.version_id),
        ).fetchall()
        if len(row["dependencies"]) > 100:
            raise WorkspaceError(409, "Metric definition dependency bound exceeded")
    return row


def dependency(row, relation, identity, kind):
    matches = [d for d in row["dependencies"] if d["relation"] == relation]
    if (
        len(matches) != 1
        or str(matches[0]["resource_id"]) != str(identity)
        or matches[0]["object_type"] != kind
        or matches[0]["authority_state"] != "APPROVED"
        or matches[0].get("evidence_class") == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(409, "Metric exact dependency unavailable")
    return matches[0]


def timestamp(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_snapshot(metric, snapshot):
    now = datetime.now(UTC)
    if snapshot.valid_at > now or snapshot.known_at > now:
        raise ValueError("Metric definition snapshot cannot be in the future")
    if (
        timestamp(metric["system_from"]) > snapshot.known_at
        or timestamp(metric["valid_from"]) > snapshot.valid_at
        or (metric.get("valid_to") and timestamp(metric["valid_to"]) <= snapshot.valid_at)
    ):
        raise ValueError("Metric definition outside requested definition snapshot")


def assemble(principal, request: ObserveRequest, metric: dict[str, Any], history):
    """Pure validation/composition; values originate only in the verified retained output."""
    try:
        if (
            pin(metric) != request.metric
            or metric["object_type"] != "MetricDefinition"
            or metric["authority_state"] != "APPROVED"
            or metric.get("evidence_class") == "REFERENCE_TEMPLATE"
        ):
            raise ValueError("Metric pin differs")
        attrs = metric["attributes"]
        if "definition" not in attrs or "function_id" not in attrs:
            raise WorkspaceError(409, "Legacy MetricDefinition is not executable")
        spec = MetricDefinition.model_validate(attrs["definition"])
        fn = dependency(metric, "FIELD:function_id", attrs["function_id"], "FunctionDefinition")
        company = (
            pin(
                dependency(metric, "FIELD:legal_entity_id", attrs["legal_entity_id"], "LegalEntity")
            )
            if attrs.get("legal_entity_id")
            else None
        )
        if company and str(company.resource_id) != principal.scope.legal_entity_id:
            raise ValueError("Metric company differs from selected company scope")
        if isinstance(spec.unit, CurrencyUnit) and (
            pin(dependency(metric, "METRIC_UNIT", spec.unit.reference.resource_id, "Currency"))
            != spec.unit.reference
        ):
            raise ValueError("Metric unit changed")
        if (
            history["status"] != "SUCCEEDED"
            or history["invocation_id"] != str(request.invocation_id)
            or history["receipt_hash"] != request.expected_receipt_hash
        ):
            raise ValueError("Completed invocation receipt differs")
        receipt, output = history["receipt"], history["output"]
        if any(
            evidence.get(flag) is not False
            for evidence in (receipt, output)
            for flag in ("current_use_authorized", "business_effect_authorized")
        ):
            raise ValueError("Metric requires explicitly non-authoritative source evidence")
        scope = principal.scope.model_dump(mode="json")
        if (
            receipt["exact_scope"] != scope
            or output["scope"] != scope
            or output["calculation_runtime"] != "shared-functions/1"
            or receipt["run_id"] != output["run_id"]
            or output["invocation_request_id"] != str(request.invocation_id)
            or str(receipt["request"]["request_id"]) != str(request.invocation_id)
            or receipt["plan_hash"] != output["invocation_plan_hash"]
            or receipt["implementation"] != output["implementation"]
            or pin(receipt["function"]) != pin(fn)
            or pin(output["function"]) != pin(fn)
        ):
            raise ValueError("Metric Function result binding differs")
        for key in ("valid_at", "known_at"):
            if timestamp(receipt["request"][key]) != getattr(request, key):
                raise ValueError("Invocation time differs")
        definition_snapshot = request.definition_snapshot or DefinitionSnapshot(
            valid_at=request.valid_at, known_at=request.known_at
        )
        validate_snapshot(metric, definition_snapshot)
        if isinstance(spec.selector, ObjectCount):
            if (
                fn["attributes"]["definition"]["implementation_id"]
                != "ontology.object-set-derived/v1"
                or bool(company) != bool(spec.selector.company_field)
                or output["contract"] != "function-result/1"
                or output["coverage"] != "COMPLETE_BOUNDED_MATERIALIZATION"
                or output["query"]["offset"] != 0
                or output.get("next_offset") is not None
                or type(output["total"]) is not int
                or output["total"] != len(output["objects"])
            ):
                raise ValueError("Object count needs complete bounded materialization")
            for key in ("valid_at", "known_at"):
                if timestamp(output["query"][key]) != getattr(request, key):
                    raise ValueError("Count query time differs")
            members = [pin(obj) for obj in output["objects"]]
            if company:
                filters = output["query"].get("filters", [])
                if not any(
                    f.get("field") == spec.selector.company_field
                    and f.get("operator") == "eq"
                    and str(f.get("value")) == str(company.resource_id)
                    for f in filters
                ):
                    raise ValueError("Company count requires exact query predicate")
                if any(
                    str(obj["attributes"].get(spec.selector.company_field))
                    != str(company.resource_id)
                    for obj in output["objects"]
                ):
                    raise ValueError("Count includes another company")
            value = MetricOutput(
                key="object_count",
                state="VALUE",
                value=str(output["total"]),
                unit=spec.unit,
                grain=spec.grain,
                dimensions=spec.dimensions,
                company=company,
                valid_at=request.valid_at,
                known_at=request.known_at,
                coverage="COMPLETE",
                contributors=members,
            )
        else:
            outputs = [MetricOutput.model_validate(v) for v in output.get("metric_outputs", [])]
            if len(outputs) > 100 or len({v.key for v in outputs}) != len(outputs):
                raise ValueError("Metric output keys ambiguous or unbounded")
            matches = [v for v in outputs if v.key == spec.selector.key]
            if len(matches) != 1:
                raise ValueError("Metric output unavailable")
            value = matches[0]
        if (
            value.state != "VALUE"
            or value.unit != spec.unit
            or value.grain != spec.grain
            or value.dimensions != spec.dimensions
            or value.company != company
            or value.valid_at != request.valid_at
            or value.known_at != request.known_at
        ):
            raise ValueError("Metric output contract differs from accepted definition")
        return {
            "contract": "metric-observation/1",
            "metric": request.metric.model_dump(mode="json"),
            "function": pin(fn).model_dump(mode="json"),
            "invocation_id": str(request.invocation_id),
            "input_run_id": output["run_id"],
            "input_receipt_hash": history["receipt_hash"],
            "input_plan_hash": receipt["plan_hash"],
            "definition": spec.model_dump(mode="json"),
            "definition_snapshot": definition_snapshot.model_dump(mode="json"),
            "observation": value.model_dump(mode="json"),
            # Preserve complete source/accounting context, not only a selected display value.
            "source_result": output,
            "current_use_authorized": False,
            "business_effect_authorized": False,
        }
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise WorkspaceError(
            409, "Metric observation requires complete exact compatible evidence"
        ) from exc


def observe(principal, request: ObserveRequest):
    require_permission(principal, "ontology_read")
    metric = definition(principal, request.metric)
    retained = function_invocations.history(principal, request.invocation_id)
    result = assemble(principal, request, metric, retained)
    return fact_runs.retain_run(principal, result, runtime=RUNTIME)


def history(principal, observation_id):
    require_permission(principal, "ontology_read")
    result = fact_runs.read_run(principal, observation_id)
    if (
        result.get("contract") != "metric-observation/1"
        or result.get("calculation_runtime") != RUNTIME
    ):
        raise WorkspaceError(404, "Metric observation unavailable")
    return result
