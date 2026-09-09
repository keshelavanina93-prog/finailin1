"""Load ChartPack data and prepare unapproved account classifications.

The service is deliberately independent of a company name or a particular
workbook.  It consumes the retained row shape produced by any compatible
1C turnover trial-balance adapter and emits ordinary ``ResourceProposal``
objects.  A proposal contains source hashes and source-row coordinates, but
it never creates journals or changes canonical authority by itself.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from finai_api.domain.finance_chartpack import (
    AccountClassification,
    AnalyticPolicy,
    ChartPack,
)
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

PACK_FILE = "chartpack.1c_ge_statutory.v1.json"
PACK_ID = "chartpack.1c_ge_statutory.v1"
CONTRACT = "account-classification-proposal/1"
SOURCE_HASH = re.compile(r"^[a-f0-9]{64}$")


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _pack_file(pack_id: str) -> Path:
    if pack_id != PACK_ID:
        raise WorkspaceError(404, f"ChartPack {pack_id!r} is not installed as a proposal library")
    packaged = files("finai_api").joinpath("catalog", PACK_FILE)
    if packaged.is_file():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[5] / "packages/contracts/catalog" / PACK_FILE


def load_chartpack(pack_id: str = PACK_ID) -> ChartPack:
    """Load and validate a declarative ChartPack from the packaged catalog."""

    path = _pack_file(pack_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        pack = ChartPack.model_validate(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkspaceError(503, "ChartPack proposal library is invalid") from exc
    if pack.pack_id != pack_id or pack.mapping_status != "proposed":
        raise WorkspaceError(503, "ChartPack proposal library has an invalid authority state")
    return pack


# The spelling without the underscore is used by the domain documentation;
# keep both names stable for callers that treat the pack as a package resource.
load_chart_pack = load_chartpack


def _normalize_account_code(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _analytic_mapping(
    policy: AnalyticPolicy, value: Any
) -> tuple[str | None, str, list[str]]:
    observed = _normalize_account_code(value)
    if not observed:
        return None, "NOT_APPLICABLE", []
    # 1C analytic labels commonly carry a human-readable suffix after the
    # account/key token (for example ``1111111 - Rustavi``).  The ChartPack
    # pattern is intentionally defined over that token, so match both the
    # complete label and its leading token without weakening the declarative
    # pattern for ordinary values.
    observed_head = observed.split(" - ", 1)[0].strip()
    matches = [
        rule
        for rule in policy.rules
        if any(
            re.fullmatch(rule.source_pattern, candidate) is not None
            for candidate in (observed, observed_head)
        )
        or re.match(rule.source_pattern.removesuffix("$"), observed) is not None
    ]
    if matches:
        return (
            sorted(matches, key=lambda rule: (-rule.priority, rule.key))[0].dimension,
            "MAPPED_CANDIDATE",
            [],
        )
    return policy.default_dimension, "UNMAPPED_OBSERVED", ["UNMAPPED_SUBKONTO"]


def _analytic_dimension(policy: AnalyticPolicy, value: Any) -> str | None:
    """Compatibility helper returning only the proposed dimension label."""

    return _analytic_mapping(policy, value)[0]


def _account_pattern_matches(pattern: str, value: str) -> bool:
    """Match a source chart code, including 1C's ``X`` group placeholders.

    A code such as ``141X`` is an observed account-group label, not a literal
    account.  Expanding at most four placeholders keeps this bounded while
    allowing the declarative pack's numeric patterns to remain reusable.
    """

    if "X" not in value.upper():
        return re.fullmatch(pattern, value) is not None
    positions = [index for index, char in enumerate(value.upper()) if char == "X"]
    if len(positions) > 4:
        return False
    candidates = [value]
    for position in positions:
        candidates = [
            candidate[:position] + str(digit) + candidate[position + 1 :]
            for candidate in candidates
            for digit in range(10)
        ]
    return any(re.fullmatch(pattern, candidate) is not None for candidate in candidates)


def _classification(
    account_code: Any,
    *,
    subkonto: Any = None,
    additive_ok: bool = True,
    duplicate_of: int | None = None,
    pack: ChartPack,
) -> AccountClassification:
    raw = "" if account_code is None else str(account_code)
    normalized = _normalize_account_code(account_code)
    if not normalized:
        observation_codes = ["UNMAPPED_ACCOUNT_CODE"]
        if _normalize_account_code(subkonto):
            observation_codes.append("UNMAPPED_SUBKONTO")
        return AccountClassification(
            account_code=raw,
            normalized_account_code="",
            state="UNMAPPED",
            additive_ok=additive_ok,
            duplicate_of=duplicate_of,
            reason="Source row has no account code; retain it as an observed row.",
            analytic_mapping_state="UNMAPPED_OBSERVED",
            observation_codes=observation_codes,
        )

    matches = [
        rule for rule in pack.rules if _account_pattern_matches(rule.account_pattern, normalized)
    ]
    if not matches:
        observation_codes = ["UNMAPPED_ACCOUNT_CODE"]
        if _normalize_account_code(subkonto):
            observation_codes.append("UNMAPPED_SUBKONTO")
        return AccountClassification(
            account_code=raw,
            normalized_account_code=normalized,
            state="UNMAPPED",
            additive_ok=additive_ok,
            duplicate_of=duplicate_of,
            reason="No ChartPack rule matches the observed account code.",
            analytic_mapping_state="UNMAPPED_OBSERVED",
            observation_codes=observation_codes,
        )

    priority = max(rule.priority for rule in matches)
    top = [rule for rule in matches if rule.priority == priority]
    semantics = {
        (
            rule.local_account_class,
            rule.statement_line,
            rule.flow_measure,
            rule.balance_measure,
            rule.analytic_policy,
        )
        for rule in top
    }
    if len(semantics) > 1:
        return AccountClassification(
            account_code=raw,
            normalized_account_code=normalized,
            state="AMBIGUOUS",
            additive_ok=additive_ok,
            duplicate_of=duplicate_of,
            reason="Multiple highest-priority ChartPack rules match the account code.",
        )
    rule = sorted(top, key=lambda item: item.key)[0]
    policy = next(
        (item for item in pack.analytic_policies if item.key == rule.analytic_policy), None
    )
    if policy:
        analytic_dimension, analytic_mapping_state, observation_codes = _analytic_mapping(
            policy, subkonto
        )
    elif subkonto is not None and _normalize_account_code(subkonto):
        analytic_dimension, analytic_mapping_state, observation_codes = (
            None,
            "UNMAPPED_OBSERVED",
            ["UNMAPPED_SUBKONTO"],
        )
    else:
        analytic_dimension, analytic_mapping_state, observation_codes = None, "NOT_APPLICABLE", []
    return AccountClassification(
        account_code=raw,
        normalized_account_code=normalized,
        state="CLASSIFICATION_UNREVIEWED",
        rule_key=rule.key,
        local_account_class=rule.local_account_class,
        statement_line=rule.statement_line,
        flow_measure=rule.flow_measure,
        balance_measure=rule.balance_measure,
        analytic_policy=rule.analytic_policy,
        analytic_dimension=analytic_dimension,
        analytic_mapping_state=analytic_mapping_state,
        observation_codes=observation_codes,
        operating=rule.operating,
        additive_ok=additive_ok,
        duplicate_of=duplicate_of,
        reason=(
            "ChartPack match is a proposed mapping; independent review is required before use."
        ),
    )


def classify_account(
    account_code: Any,
    *,
    subkonto: Any = None,
    additive_ok: bool = True,
    duplicate_of: int | None = None,
    pack: ChartPack | None = None,
) -> AccountClassification:
    """Classify one observed code without granting accounting authority."""

    return _classification(
        account_code,
        subkonto=subkonto,
        additive_ok=additive_ok,
        duplicate_of=duplicate_of,
        pack=pack or load_chartpack(),
    )


def classify_tb_row(row: Any, *, pack: ChartPack | None = None) -> dict[str, Any]:
    """Return a source-linked, unreviewed classification for one retained row."""

    selected = pack or load_chartpack()
    result = _classification(
        _row_value(row, "account_code", _row_value(row, "code")),
        subkonto=_row_value(row, "subkonto"),
        additive_ok=bool(_row_value(row, "additive_ok", True)),
        duplicate_of=_row_value(row, "duplicate_of"),
        pack=selected,
    )
    coordinates = _row_value(row, "coordinates", {})
    source_coordinates = dict(coordinates) if isinstance(coordinates, Mapping) else {}
    return {
        "source_row": _row_value(row, "source_row"),
        "account_code": _row_value(row, "account_code", _row_value(row, "code")),
        "account_name": _row_value(row, "account_name", _row_value(row, "name")),
        "subkonto": _row_value(row, "subkonto"),
        "outline_role": _row_value(row, "outline_role"),
        "coordinates": source_coordinates,
        "classification": result.model_dump(mode="json"),
    }


def classify_tb_rows(rows: Iterable[Any], *, pack: ChartPack | None = None) -> list[dict[str, Any]]:
    """Classify rows in source order; duplicate and non-additive rows survive."""

    selected = pack or load_chartpack()
    return [classify_tb_row(row, pack=selected) for row in rows]


def _rows_from_months(months_or_rows: Iterable[Any]) -> list[Any]:
    rows: list[Any] = []
    for item in months_or_rows:
        candidate = _row_value(item, "rows")
        if candidate is None:
            rows.append(item)
        else:
            rows.extend(candidate)
    return rows


def _validated_source_hashes(source_hashes: Sequence[str]) -> tuple[str, ...]:
    values = tuple(sorted(set(source_hashes)))
    if not values or any(SOURCE_HASH.fullmatch(value) is None for value in values):
        raise WorkspaceError(
            422, "Classification requires one or more lowercase source SHA-256 hashes"
        )
    return values


def classification_manifest(
    rows: Iterable[Any],
    *,
    source_family: str,
    source_hashes: Sequence[str],
    pack: ChartPack | None = None,
) -> dict[str, Any]:
    """Build a deterministic, review-ready manifest without database writes."""

    if not source_family.strip():
        raise WorkspaceError(422, "Classification requires a source family")
    selected = pack or load_chartpack()
    hashes = _validated_source_hashes(source_hashes)
    classified = classify_tb_rows(_rows_from_months(rows), pack=selected)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in classified:
        code = _normalize_account_code(entry["account_code"])
        key = code or f"__ROW__:{entry['source_row']}"
        grouped[key].append(entry)
    accounts = []
    observation_findings: list[dict[str, Any]] = []
    for code, entries in grouped.items():
        first = entries[0]
        classifications = [item["classification"] for item in entries]
        for item in entries:
            for observation_code in item["classification"]["observation_codes"]:
                observation_findings.append(
                    {
                        "code": observation_code,
                        "source_row": item["source_row"],
                        "account_code": item["account_code"],
                        "subkonto": item["subkonto"],
                        "coordinates": item["coordinates"],
                        "state": "OBSERVED",
                    }
                )
        additive_ok = all(bool(item["classification"]["additive_ok"]) for item in entries)
        accounts.append(
            {
                "account_code": first["account_code"],
                "normalized_account_code": code.removeprefix("__ROW__:")
                if code.startswith("__ROW__:")
                else code,
                "source_rows": [item["source_row"] for item in entries],
                "source_coordinates": [item["coordinates"] for item in entries],
                "subkonto_values": [item["subkonto"] for item in entries],
                "outline_roles": [item["outline_role"] for item in entries],
                "additive_ok": additive_ok,
                "duplicate_of": [
                    item["classification"]["duplicate_of"]
                    for item in entries
                    if item["classification"]["duplicate_of"] is not None
                ],
                "classifications": classifications,
            }
        )
    accounts.sort(key=lambda item: (item["normalized_account_code"], item["source_rows"]))
    return {
        "contract": CONTRACT,
        "source_family": source_family,
        "source_hashes": list(hashes),
        "pack_id": selected.pack_id,
        "pack_version": selected.version,
        "mapping_status": "proposed",
        "classification_state": "CLASSIFICATION_UNREVIEWED",
        "authority": "CANDIDATE_ONLY",
        "observation_findings": observation_findings,
        "unmapped_account_count": sum(
            item["code"] == "UNMAPPED_ACCOUNT_CODE" for item in observation_findings
        ),
        "unmapped_subkonto_count": sum(
            item["code"] == "UNMAPPED_SUBKONTO" for item in observation_findings
        ),
        "accounts": accounts,
    }


def classification_proposal_id(principal: Principal, manifest: Mapping[str, Any]) -> UUID:
    """Derive a stable UUID from the exact scope, pack and source evidence."""

    digest = _digest(
        {
            "tenant_id": str(principal.scope.tenant_id),
            "legal_entity_id": principal.scope.legal_entity_id,
            "manifest": manifest,
        }
    )
    return uuid5(principal.scope.tenant_id, "chartpack-classification:" + digest)


def prepare_classification_proposal(
    principal: Principal,
    rows: Iterable[Any],
    *,
    source_family: str,
    source_hashes: Sequence[str],
    rationale: str,
    pack: ChartPack | None = None,
    valid_from: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
    source_versions: Mapping[UUID, Mapping[UUID, UUID]] | None = None,
) -> ResourceProposal:
    """Prepare one bounded candidate classification proposal.

    This function performs no database mutation.  Callers submit the returned
    proposal through ``resources.propose`` so the existing independent review,
    immutable decision, and receipt machinery remains authoritative.
    """

    if offset < 0 or limit < 1 or limit > 100:
        raise WorkspaceError(422, "Classification proposal pages must be between 1 and 100 rows")
    if valid_from is None:
        valid_from = datetime.now(UTC)
    elif valid_from.tzinfo is None or valid_from.utcoffset() is None:
        raise WorkspaceError(422, "Classification effective time requires an explicit timezone")
    if len(rationale.strip()) < 10:
        raise WorkspaceError(422, "Classification rationale needs ten non-padding characters")

    manifest = classification_manifest(
        rows,
        source_family=source_family,
        source_hashes=source_hashes,
        pack=pack,
    )
    accounts = manifest["accounts"][offset : offset + limit]
    if not accounts:
        raise WorkspaceError(422, "No classification rows in the requested proposal page")
    manifest = {**manifest, "offset": offset, "limit": limit}
    proposal_id = classification_proposal_id(principal, manifest)
    mutations = []
    for entry in accounts:
        key = entry["normalized_account_code"] or f"source-row-{entry['source_rows'][0]}"
        identity_key = (
            f"{manifest['pack_id']}:{manifest['pack_version']}:{manifest['source_family']}:{key}"
        )
        identity = uuid5(proposal_id, "classification:" + key)
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                object_type="AccountClassificationProposal",
                identity_key=identity_key,
                display_name=(f"{entry['account_code'] or '[unmapped]'} · {manifest['pack_id']}")[
                    :200
                ],
                valid_from=valid_from,
                evidence_class="USER_ASSERTED",
                attributes={
                    "contract": CONTRACT,
                    "mapping_status": "proposed",
                    "classification_state": "CLASSIFICATION_UNREVIEWED",
                    "authority": "CANDIDATE_ONLY",
                    "source_family": manifest["source_family"],
                    "source_hashes": manifest["source_hashes"],
                    "pack_id": manifest["pack_id"],
                    "pack_version": manifest["pack_version"],
                    "account_code": entry["account_code"],
                    "normalized_account_code": entry["normalized_account_code"],
                    "source_rows": entry["source_rows"],
                    "source_coordinates": entry["source_coordinates"],
                    "subkonto_values": entry["subkonto_values"],
                    "outline_roles": entry["outline_roles"],
                    "additive_ok": entry["additive_ok"],
                    "duplicate_of": entry["duplicate_of"],
                    "classifications": entry["classifications"],
                    "observation_findings": [
                        finding
                        for finding in manifest["observation_findings"]
                        if finding["source_row"] in entry["source_rows"]
                    ],
                    "review": {
                        "required": True,
                        "submitter_must_differ_from_reviewer": True,
                        "decision_immutable": True,
                    },
                },
            )
        )
    return ResourceProposal(
        proposal_id=proposal_id,
        title=f"Review {manifest['pack_id']} account classifications",
        rationale=(
            rationale.strip()
            + " Mapping is proposed from retained source rows; source hashes and coordinates "
            "are pinned and no journal authority is created."
        ),
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
        source_versions=dict(source_versions or {}),
    )


def submit_classification_proposal(principal: Principal, proposal: ResourceProposal) -> Any:
    """Submit a prepared proposal through the shared governed lifecycle."""

    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    return resources.propose(principal, proposal)


# Descriptive aliases keep the service discoverable without introducing a
# company-specific implementation module.
build_classification_proposal = prepare_classification_proposal
propose_classifications = submit_classification_proposal
