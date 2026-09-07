"""Shared retained-posting Function: reviewed meaning, exact numerals and source drill."""

from datetime import datetime
from decimal import Decimal, DecimalException, Inexact, localcontext
from uuid import UUID

from finai_api.domain.function_execution import PostedMovementsImplementation
from finai_api.domain.resource_lifecycle import ConsumptionRequest, VersionReference
from finai_api.services.accounting_consumption import require_accounting_bindings
from finai_api.services.accounting_source_document import read_source
from finai_api.services.resource_lifecycle import consume
from finai_api.services.seg_expense_source import read_base
from finai_api.services.source_accounting_context import validate_active_selection
from finai_api.services.workspace import WorkspaceError


def _pin(row):
    return {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}


def discover(principal, binding_id, document_id, sheet):
    from finai_api.services.resources import list_resources

    return [
        {
            "resource_id": str(row.resource_id),
            "version_id": str(row.version_id),
            "display_name": row.display_name,
        }
        for row in list_resources(principal, "FunctionDefinition", "", 0, limit=1000)
        if row.attributes.get("accounting_binding_id") == binding_id
        and row.attributes.get("definition", {}).get("implementation_id")
        == "accounting.retained-posted-movements/v1"
        and row.attributes["definition"].get("document_id") == document_id
        and row.attributes["definition"].get("sheet") == sheet
    ]


def validate_definition(spec, target):
    adapter = spec.definition
    assert isinstance(adapter, PostedMovementsImplementation)
    binding = target(str(spec.accounting_binding_id))
    scope = target(str(spec.source_scope_id))
    evidence = target(str(spec.evidence_id))
    attrs = binding["attributes"]
    source = scope["attributes"]
    if (
        binding["object_type"] != "SourceAccountingBinding"
        or scope["object_type"] != "SourceAccountingScope"
        or evidence["object_type"] != "SourceEvidence"
        or attrs.get("scope_id") != str(spec.source_scope_id)
        or source.get("evidence_id") != str(spec.evidence_id)
        or source.get("document_id") != adapter.document_id
        or source.get("worksheet") != adapter.sheet
        or source.get("source_profile") != "seg_expense_base"
        or evidence["attributes"].get("sha256") != adapter.source_sha256
    ):
        raise WorkspaceError(409, "Posted movements require matching source, scope and binding")
    validate_active_selection(attrs, source, target)
    mapping = target(attrs["account_mapping_id"])
    dimensions = target(attrs["dimension_mapping_id"])
    rule = mapping["attributes"].get("definition", {})
    dimension_rule = dimensions["attributes"].get("definition", {})
    if (
        rule.get("kind") != "EXACT_SOURCE_ACCOUNT_IDENTITIES"
        or rule.get("version") != 1
        or rule.get("company_id") != source["legal_entity_id"]
        or rule.get("chart_id") != source["chart_id"]
        or not isinstance(rule.get("accounts"), dict)
        or not 1 <= len(rule["accounts"]) <= 100
        or dimension_rule.get("kind") != "PRESERVE_SOURCE_DIMENSION_COORDINATES"
        or dimension_rule.get("company_id") != source["legal_entity_id"]
        or dimension_rule.get("aggregation_dimensions") != []
    ):
        raise WorkspaceError(409, "Posted movements require reviewed exact source mapping rules")
    # Resolve every mapping through canonical dependency recording at publication.
    for code, ref in rule["accounts"].items():
        account = target(ref["resource_id"])
        if (
            account["object_type"] != "LocalAccount"
            or str(account["version_id"]) != ref["version_id"]
            or account["attributes"].get("account_code") != code
            or account["attributes"].get("chart_id") != source["chart_id"]
        ):
            raise WorkspaceError(409, "Account mapping requires exact reviewed account versions")
    return binding, scope, evidence, rule


def source_plan(principal, request, spec, pins):
    def target(identity):
        row = pins.get(str(identity))
        if row is None:
            raise WorkspaceError(409, "Posted movement input exact version is unavailable")
        return row

    binding, scope, evidence, rule = validate_definition(spec, target)
    if request.offset != 0 or request.input_result is not None:
        raise WorkspaceError(422, "Posted movements consume one complete bounded source snapshot")
    if any(row["system_from"] > request.known_at for row in pins.values()):
        raise WorkspaceError(409, "Accounting configuration was unavailable at knowledge time")
    used = {(UUID(str(scope["resource_id"])), UUID(str(scope["version_id"])))}
    direct = {
        (UUID(str(row["resource_id"])), UUID(str(row["version_id"]))) for row in pins.values()
    }
    require_accounting_bindings(principal, used, direct)
    adapter = spec.definition
    metadata, content = read_source(principal, adapter.document_id)
    if metadata["source_sha256"] != adapter.source_sha256:
        raise WorkspaceError(409, "Posted movement source hash changed")
    retained_at = metadata.get("source_snapshot", {}).get("ingested_at")
    if retained_at is not None:
        known = datetime.fromisoformat(retained_at) if isinstance(retained_at, str) else retained_at
        if known > request.known_at:
            raise WorkspaceError(409, "Source snapshot was unavailable at knowledge time")
    parsed = read_base(content, adapter.sheet)
    if len(parsed["rows"]) > adapter.max_source_rows:
        raise WorkspaceError(409, "Retained posting source exceeds the reviewed row budget")
    if not parsed["posting_identity_ready"]:
        raise WorkspaceError(409, "Duplicate recorder identities require source review")
    return {
        "document_id": adapter.document_id,
        "sha256": adapter.source_sha256,
        "filename": metadata["filename"],
        "sheet": adapter.sheet,
        "row_count": len(parsed["rows"]),
        "max_source_rows": adapter.max_source_rows,
        "evidence": _pin(evidence),
        "binding": _pin(binding),
        "scope": _pin(scope),
        "context": {
            key: binding["attributes"][key]
            for key in (
                "ledger_id",
                "book_id",
                "period_id",
                "currency_id",
                "functional_currency_id",
                "amount_field",
                "amount_semantics",
                "vat_treatment",
            )
        },
        "company_id": scope["attributes"]["legal_entity_id"],
        "observed_from": scope["attributes"]["observed_from"],
        "observed_through": scope["attributes"]["observed_through"],
        "accounts": rule["accounts"],
    }


def calculate(parsed, source):
    """Deterministic adapter kernel. Coordinates are source evidence, never object IDs."""
    if parsed["source_sha256"] != source["sha256"] or parsed["sheet"] != source["sheet"]:
        raise WorkspaceError(409, "Calculation source does not match its retained plan")
    if not parsed["posting_identity_ready"]:
        raise WorkspaceError(409, "Duplicate recorder identities cannot enter accounting totals")
    if len(parsed["rows"]) != source["row_count"]:
        raise WorkspaceError(409, "Calculation must retain the complete reviewed source snapshot")
    headers = [
        coordinate for coordinate, cell in parsed["headers"].items() if cell["value"] == "Сумма"
    ]
    if len(headers) != 1:
        raise WorkspaceError(409, "An exact posted amount header is required")
    amount_column = headers[0].removesuffix("1")
    groups, excluded, included = {}, [], []
    with localcontext() as context:
        context.prec = 50
        context.traps[Inexact] = True
        for row in parsed["rows"]:
            attrs = row["attributes"]
            if not source["observed_from"] <= attrs["posting_date"] <= source["observed_through"]:
                raise WorkspaceError(409, "Posting date differs from the bound source period")
            sides = {"debit": attrs["account_code"], "credit": attrs["credit_account_code"]}
            if any(code not in source["accounts"] for code in sides.values()):
                raise WorkspaceError(409, "An observed account lacks an exact reviewed mapping")
            observation = row["numeric_observations"].get("source_amount", {})
            coordinate = amount_column + str(row["row"])
            amount = observation.get("literal_decimal")
            if amount is None:
                excluded.append(
                    {
                        "row": row["row"],
                        "coordinate": coordinate,
                        "reason": "MISSING_LITERAL_POSTED_AMOUNT",
                    }
                )
                continue
            if (
                observation.get("coordinate") != coordinate
                or observation.get("formula") is not None
            ):
                raise WorkspaceError(409, "Posted amount must retain its original literal cell")
            try:
                value = Decimal(amount)
                # Bound expansion of hostile exponents before serializing exact sums.
                if (
                    not value.is_finite()
                    or abs(value.adjusted()) > 100
                    or len(value.as_tuple().digits) > 50
                ):
                    raise ValueError("Unbounded decimal")
                for side, code in sides.items():
                    key = (code, side)
                    group = groups.setdefault(
                        key,
                        {
                            "account_code": code,
                            "account": source["accounts"][code],
                            "side": side,
                            "value": Decimal(0),
                            "source_coordinates": [],
                        },
                    )
                    group["value"] += value
                    group["source_coordinates"].append(coordinate)
            except (DecimalException, ValueError) as exc:
                raise WorkspaceError(422, "Posted movement exceeds exact decimal bounds") from exc
            included.append(coordinate)
    return {
        "groups": [
            {
                **group,
                "value": format(group["value"], "f"),
                "currency_id": source["context"]["currency_id"],
            }
            for _, group in sorted(groups.items())
        ],
        "included_coordinates": included,
        "excluded_rows": excluded,
        "coverage": {
            "source_rows": len(parsed["rows"]),
            "included_rows": len(included),
            "excluded_rows": len(excluded),
            "ledger_completeness": "UNESTABLISHED",
        },
    }


def execute(principal, request, plan):
    source = plan["source_document"]
    metadata, content = read_source(principal, source["document_id"])
    if metadata["source_sha256"] != source["sha256"]:
        raise WorkspaceError(409, "Retained source hash changed before calculation")
    parsed = read_base(content, source["sheet"])
    result = calculate(parsed, source)
    proof = consume(
        principal,
        ConsumptionRequest(
            consumer=request.function,
            inputs=[
                VersionReference(
                    resource_id=UUID(pin["resource_id"]), version_id=UUID(pin["version_id"])
                )
                for pin in plan["static_dependencies"]
            ],
            minimum_state="OBSERVED",
        ),
    )
    return {
        "contract": "function-result/1",
        "function": plan["function"],
        "implementation": plan["implementation"],
        "plan_hash": plan["plan_hash"],
        "source_document": source,
        "source_rows": parsed["rows"],
        "returned_rows": len(parsed["rows"]),
        "next_offset": None,
        "objects": [],
        "derived_values": [],
        "used_versions": [],
        "static_dependencies": plan["static_dependencies"],
        "posted_movements": result,
        "authority_check": {key: proof[key] for key in ("consumption_id", "proof_hash")},
        "query": {
            "valid_at": request.valid_at.isoformat(),
            "known_at": request.known_at.isoformat(),
            "offset": request.offset,
            "limit": request.limit,
        },
        "coverage": "RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS",
        "authority": "GUARDED_POSTED_MOVEMENT_ANALYSIS",
        "temporal_semantics": "IMMUTABLE_RETAINED_SNAPSHOT_WITH_POSTING_DATES",
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
