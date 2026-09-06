"""Accounting ancestry requires exact, reviewed source-use authority at consumption."""

from datetime import date
from typing import Any, NoReturn
from uuid import UUID, uuid5

from psycopg.rows import dict_row

from finai_api.domain.ontology_definitions import DEFINITION_MODELS
from finai_api.domain.resources import ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

Pin = tuple[UUID, UUID]
ACCOUNTING_KINDS = {
    "SourceJournalMovement",
    "SourceTrialBalanceRow",
    "JournalLine",
    "JournalEntry",
    "SourceAccountingScope",
}
MAX_NODES = 1000
MAX_EDGES = 5000


def _deny(message: str) -> NoReturn:
    raise WorkspaceError(409, "Accounting consumption: " + message)


def _money_matches(
    amount: dict[str, Any], binding: dict[str, Any], currency: dict[str, Any]
) -> bool:
    return bool(
        ("currency_id" in amount or "currency" in amount)
        and ("currency_id" not in amount or str(amount["currency_id"]) == binding["currency_id"])
        and ("currency" not in amount or amount["currency"] == currency.get("code"))
    )


def validate_bindings(
    rows: dict[Pin, dict[str, Any]],
    edges: list[tuple[Pin, Pin, str]],
    used: set[Pin],
    direct_pins: set[Pin],
) -> list[dict[str, str]]:
    neighbors: dict[Pin, list[Pin]] = {}
    for source, target_pin, _ in edges:
        neighbors.setdefault(source, []).append(target_pin)

    def ancestry(roots: set[Pin]) -> set[Pin]:
        seen, pending = set(roots), list(roots)
        while pending:
            for target in neighbors.get(pending.pop(), []):
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        if not seen.issubset(rows):
            _deny("immutable lineage is incomplete in the authorized context")
        return seen

    accounting = [key for key in ancestry(used) if rows[key]["object_type"] in ACCOUNTING_KINDS]
    if not accounting:
        return []
    bindings = [key for key in direct_pins if rows[key]["object_type"] == "SourceAccountingBinding"]
    if not bindings:
        _deny("an exact SourceAccountingBinding must be a direct consumer dependency")
    from finai_api.services.source_accounting_context import validate_active_selection

    active = []
    for binding_key in bindings:
        binding = rows[binding_key]
        attrs = binding["attributes"]
        if (
            binding["authority_state"] != "APPROVED"
            or attrs.get("source_use") != "ACCOUNTING_INPUT"
        ):
            _deny("source binding is not accepted for ACCOUNTING_INPUT")
        if attrs.get("contract_version") != "2":
            _deny("source binding requires the explicit version 2 accounting contract")
        field_pins = {
            relation.removeprefix("FIELD:"): target
            for source, target, relation in edges
            if source == binding_key and relation.startswith("FIELD:")
        }

        def target(
            identity: str,
            field_map: dict[str, Pin] = field_pins,
            attributes: dict[str, Any] = attrs,
        ) -> dict[str, Any]:
            matching = {
                key
                for field, key in field_map.items()
                if str(key[0]) == str(identity) and str(attributes.get(field)) == str(identity)
            }
            if len(matching) != 1:
                _deny("accounting configuration requires an unambiguous exact field pin")
            return rows[next(iter(matching))]

        scope = target(attrs.get("scope_id", ""))
        if (
            scope["object_type"] != "SourceAccountingScope"
            or scope["evidence_class"] != "SOURCE_BOUND"
        ):
            _deny("accounting binding has no source-bound scope")
        validate_active_selection(attrs, scope["attributes"], target)
        currency = target(attrs["currency_id"])
        active.append((binding_key, attrs, scope["attributes"], currency["attributes"]))
    selected: set[Pin] = set()
    source_bindings: dict[Pin, Pin] = {}
    for key in accounting:
        row, lineage = rows[key], [rows[k] for k in ancestry({key})]
        attrs, kind = row["attributes"], row["object_type"]
        company = attrs.get("legal_entity_id")
        if not company:
            companies = {
                r["attributes"].get("legal_entity_id")
                for r in lineage
                if r["object_type"] == "JournalEntry"
            }
            companies.discard(None)
            company = next(iter(companies)) if len(companies) == 1 else None
        evidence = attrs.get("evidence_id")
        if not evidence:
            evidence_ids = {
                r["attributes"].get("evidence_id")
                for r in lineage
                if r["object_type"] == "SourceRecord"
            }
            evidence_ids.discard(None)
            evidence = next(iter(evidence_ids)) if len(evidence_ids) == 1 else None
        start = attrs.get("posting_date") or attrs.get("period_start") or attrs.get("observed_from")
        end = attrs.get("posting_date") or attrs.get("period_end") or attrs.get("observed_through")
        if not company or not evidence or not start or not end:
            _deny("accounting lineage lacks explicit company, source evidence or date bounds")
        try:
            start_date, end_date = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        except ValueError:
            _deny("accounting lineage has invalid date bounds")
        matches = []
        for binding_key, binding, scope, currency in active:
            if scope.get("legal_entity_id") != company or scope.get("evidence_id") != evidence:
                continue
            if not (
                scope["observed_from"]
                <= start_date.isoformat()
                <= end_date.isoformat()
                <= scope["observed_through"]
            ):
                continue
            if any(
                attrs.get(field) is not None and attrs[field] != binding[field]
                for field in ("ledger_id", "book_id", "currency_id")
            ):
                continue
            if kind == "SourceAccountingScope" and str(key[0]) != binding["scope_id"]:
                continue
            expected_profile = {
                "SourceJournalMovement": "1c_journal",
                "SourceTrialBalanceRow": "1c_tb",
            }.get(kind)
            if expected_profile and scope.get("source_profile") != expected_profile:
                continue
            if kind == "SourceTrialBalanceRow" and binding["amount_semantics"] != "PERIOD_BALANCE":
                continue
            if kind in {"SourceJournalMovement", "JournalLine", "JournalEntry"} and binding[
                "amount_semantics"
            ] not in {"DEBIT_CREDIT", "SIGNED_MOVEMENT"}:
                continue
            amount = attrs.get(binding["amount_field"])
            if kind != "SourceAccountingScope" and amount is None:
                continue
            if isinstance(amount, dict) and not _money_matches(amount, binding, currency):
                continue
            matches.append(binding_key)
        if len(matches) != 1:
            _deny("accounting source has missing, ambiguous or incompatible active bindings")
        selected.add(matches[0])
        source_bindings[key] = matches[0]
    # A private derived type cannot relabel accounting amounts or currency while retaining
    # otherwise valid source ancestry. Use the accepted FactContract's declared unit field.
    unit_fields = {
        row["attributes"].get("definition", {}).get("unit_field")
        for key, row in rows.items()
        if key in used and row["object_type"] == "FactContract"
    } - {None}
    for key in used:
        bound = {
            source_bindings[ancestor] for ancestor in ancestry({key}) if ancestor in source_bindings
        }
        if not bound or rows[key]["object_type"] in ACCOUNTING_KINDS:
            continue
        if len(bound) != 1:
            _deny("derived accounting representation spans ambiguous source interpretations")
        _, binding, scope, currency = next(item for item in active if item[0] in bound)
        values = rows[key]["attributes"]
        for field, expected in {
            "legal_entity_id": scope["legal_entity_id"],
            "ledger_id": binding["ledger_id"],
            "book_id": binding["book_id"],
            "currency_id": binding["currency_id"],
        }.items():
            if values.get(field) is not None and str(values[field]) != str(expected):
                _deny("derived accounting context disagrees with the source interpretation")
        if binding["amount_field"] not in values:
            _deny("derived accounting measure has no compatible source amount interpretation")
        amount = values[binding["amount_field"]]
        if isinstance(amount, dict) and not _money_matches(amount, binding, currency):
            _deny("derived accounting currency disagrees with the source interpretation")
        if any(
            values.get(field) is not None and values[field] != currency.get("code")
            for field in unit_fields
        ):
            _deny("derived fact unit disagrees with the explicit source amount currency")
    return [{"resource_id": str(key[0]), "version_id": str(key[1])} for key in sorted(selected)]


def load_accounting_lineage(conn: Any, principal: Principal, roots: set[Pin]):
    """Use the caller's transaction, including canonical promotion's existing lock."""
    pending = set(roots)
    rows: dict[Pin, dict[str, Any]] = {}
    edges: list[tuple[Pin, Pin, str]] = []
    with conn.cursor(row_factory=dict_row) as cursor:
        while pending:
            if len(rows) + len(pending) > MAX_NODES:
                _deny("immutable accounting lineage exceeds the node bound")
            found = cursor.execute(
                "SELECT resource_id,version_id,object_type,attributes,"
                "authority_state,evidence_class,valid_from,valid_to "
                "FROM resource_versions WHERE tenant_id=%s AND version_id=ANY(%s::uuid[])",
                (principal.scope.tenant_id, [key[1] for key in pending]),
            ).fetchall()
            fetched = {(r["resource_id"], r["version_id"]): r for r in found}
            if set(fetched) != pending:
                _deny("immutable lineage is incomplete in the authorized context")
            rows.update(fetched)
            dependencies = cursor.execute(
                "SELECT version_id,target_resource_id,target_version_id,relation "
                "FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) LIMIT %s",
                (
                    principal.scope.tenant_id,
                    [key[1] for key in pending],
                    MAX_EDGES + 1 - len(edges),
                ),
            ).fetchall()
            source_ids = {key[1]: key for key in pending}
            next_pending = set()
            for dependency in dependencies:
                target_key = (dependency["target_resource_id"], dependency["target_version_id"])
                edges.append(
                    (source_ids[dependency["version_id"]], target_key, dependency["relation"])
                )
                if target_key not in rows:
                    next_pending.add(target_key)
            if len(edges) > MAX_EDGES:
                _deny("immutable accounting lineage exceeds the edge bound")
            pending = next_pending
    return rows, edges


def require_accounting_bindings(
    principal: Principal, used: set[Pin], direct_pins: set[Pin]
) -> list[dict[str, str]]:
    with resource_connection(principal, repeatable_read=True) as conn:
        rows, edges = load_accounting_lineage(conn, principal, used | direct_pins)
        return validate_bindings(rows, edges, used, direct_pins)


def _calculation_consumer(rows, edges, key, pins) -> bool:
    """Recognize measure-free, schema-declared authority contracts, never a caller flag alone."""
    from finai_api.services.resource_lifecycle import ORDER

    attrs = rows[key]["attributes"]
    schemas = [
        rows[target]["attributes"]
        for source, target, relation in edges
        if source == key
        and relation == "USES_SCHEMA"
        and rows[target]["object_type"] == "SchemaDefinition"
    ]
    contracts = [
        rows[pin]["attributes"].get("definition", {})
        for pin in pins
        if rows[pin]["object_type"] == "FactContract"
    ]
    if len(schemas) != 1 or not contracts or attrs.get("minimum_authority_state") not in ORDER:
        return False
    fields = schemas[0].get("fields", {})
    if fields.get("minimum_authority_state", {}).get("kind") != "identifier":
        return False
    measures = {contract.get("measure") for contract in contracts} - {None}
    measures.update(
        rows[pin]["attributes"].get("amount_field")
        for pin in pins
        if rows[pin]["object_type"] == "SourceAccountingBinding"
    )
    return not (
        measures.intersection(fields)
        or measures.intersection(attrs)
        or any(field.get("kind") in {"money", "decimal", "quantity"} for field in fields.values())
    )


def validate_accounting_proposal(
    conn: Any,
    principal: Principal,
    proposal: ResourceProposal,
    dependencies: dict[str, list[dict[str, str]]],
) -> None:
    """Check material derived objects after all proposed FIELD and source pins are resolved."""
    exempt = {
        *DEFINITION_MODELS,
        "SchemaDefinition",
        "SemanticContract",
        "LinkType",
        "SourceAccountingScope",
        "SourceAccountingBinding",
        "SourceJournalMovement",
        "SourceTrialBalanceRow",
        "SourceRecord",
        "SourceEvidence",
        "SourceAccountDefinition",
        "SourceDimensionAssignment",
        "JournalEntry",
        "JournalLine",
    }
    candidates = [item for item in proposal.mutations if item.object_type not in exempt]
    if not candidates:
        return
    proposed = {
        (item.resource_id, uuid5(proposal.proposal_id, str(item.resource_id))): item
        for item in proposal.mutations
    }
    edges = [
        (
            (UUID(identity), uuid5(proposal.proposal_id, identity)),
            (UUID(dep["resource_id"]), UUID(dep["version_id"])),
            dep["relation"],
        )
        for identity, refs in dependencies.items()
        for dep in refs
    ]
    retained_roots = {target for _, target, _ in edges if target not in proposed}
    rows, retained_edges = load_accounting_lineage(conn, principal, retained_roots)
    rows.update({key: item.model_dump(mode="json") for key, item in proposed.items()})
    edges.extend(retained_edges)
    if len(rows) > MAX_NODES or len(edges) > MAX_EDGES:
        _deny("proposed accounting lineage exceeds the supported bound")
    for item in candidates:
        key = (item.resource_id, uuid5(proposal.proposal_id, str(item.resource_id)))
        pins = {target for source, target, _ in edges if source == key}
        is_consumer = _calculation_consumer(rows, edges, key, pins)
        material_inputs = {
            pin for pin in pins if rows[pin]["object_type"] != "SourceAccountingBinding"
        }
        selected = validate_bindings(rows, edges, material_inputs if is_consumer else {key}, pins)
        if selected:
            from finai_api.services.accounting_promotion import validate_current_binding

            for ref in selected:
                binding_key = (UUID(ref["resource_id"]), UUID(ref["version_id"]))
                if binding_key in proposed:
                    _deny("co-proposed accounting bindings are not existing accepted authority")
                if is_consumer:
                    config = rows[binding_key]["attributes"]
                    scopes = [
                        rows[target]["attributes"]
                        for source, target, relation in edges
                        if source == binding_key and relation == "FIELD:scope_id"
                    ]
                    if len(scopes) != 1:
                        _deny("consumer accounting scope is ambiguous")
                    for field, expected in {
                        "legal_entity_id": scopes[0]["legal_entity_id"],
                        "ledger_id": config["ledger_id"],
                        "book_id": config["book_id"],
                        "currency_id": config["currency_id"],
                    }.items():
                        if item.attributes.get(field) is not None and str(
                            item.attributes[field]
                        ) != str(expected):
                            _deny(
                                "calculation consumer context disagrees with source interpretation"
                            )
                validate_current_binding(conn, principal, rows[binding_key])
