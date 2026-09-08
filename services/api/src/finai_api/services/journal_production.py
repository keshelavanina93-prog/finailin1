"""Governed source-row journal production through shared canonical maker/checker.

Preflight is advisory. Submission and approval repeat the canonical guards under
their transaction locks. Nothing here creates policies, rounds amounts or posts ERP.
"""

from types import SimpleNamespace
from uuid import UUID, uuid5

from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import resources, semantic_analysis
from finai_api.services.accounting_promotion import validate_journal
from finai_api.services.entity_movement_review import digest
from finai_api.services.semantic_analysis_movements import build
from finai_api.services.workspace import WorkspaceError


def blocker(code, object_type, detail, **reference):
    return {
        "code": code,
        "detail": detail,
        "required_authority": {"object_type": object_type, **reference},
    }


def compile_row(pair, source, targets, request, access_entity):
    """Build one complete canonical proposal, or explicit source-policy blockers."""
    coordinate = pair["source_coordinate"]
    issues = []
    for issue in pair["promotion_blockers"]:
        if issue["code"] == "JOURNAL_PUBLICATION_CONTEXT_UNAVAILABLE":
            issues.append(
                blocker(
                    "SOURCE_JOURNAL_SEMANTICS_UNSUPPORTED",
                    "SourceAccountingScope",
                    issue["detail"],
                    **source["scope"],
                )
            )
        if issue["code"] == "CANONICAL_JOURNAL_AMOUNT_CONTRACT_UNSUPPORTED":
            issues.append(
                blocker(
                    "EXACT_AMOUNT_CONTRACT_UNSUPPORTED",
                    "SchemaDefinition",
                    issue["detail"],
                    identity_key="JournalLine",
                    field="amount",
                )
            )
    dimensions = request.policies.get(coordinate)
    if dimensions is None:
        for line in pair["lines"]:
            issues.append(
                blocker(
                    "REVIEWED_SIDE_DIMENSIONS_REQUIRED",
                    "AccountDimensionPolicy",
                    "Supply an exact reviewed policy and explicit side assignments",
                    account=line["account"],
                    side=line["side"],
                )
            )
    if issues:
        return {"coordinate": coordinate, "state": "BLOCKED", "blockers": issues}, None
    identity = UUID(pair["proposed_entry_id"])
    record_id = uuid5(UUID(source["evidence"]["resource_id"]), coordinate)
    record_attrs = {"evidence_id": source["evidence"]["resource_id"], "coordinate": coordinate}
    entry_attrs = pair["entry"]
    definitions = [
        (record_id, "SourceRecord", record_attrs),
        (identity, "JournalEntry", entry_attrs),
    ]
    if dimensions.source_record is not None:
        reference = dimensions.source_record
        retained = targets[str(reference.resource_id)]
        if (
            str(retained["version_id"]) != str(reference.version_id)
            or retained["object_type"] != "SourceRecord"
            or retained["authority_state"] != "APPROVED"
            or retained["evidence_class"] != "SOURCE_BOUND"
            or retained["attributes"] != record_attrs
        ):
            return {
                "coordinate": coordinate,
                "state": "BLOCKED",
                "blockers": [
                    blocker(
                        "EXACT_SOURCE_RECORD_REQUIRED",
                        "SourceRecord",
                        "Reviewed record must identify this exact retained source cell",
                        **reference.model_dump(mode="json"),
                    )
                ],
            }, None
        record_id = reference.resource_id
        definitions = definitions[1:]
    for line in pair["lines"]:
        policy = getattr(dimensions, line["side"].lower())
        definitions.append(
            (
                UUID(line["proposed_resource_id"]),
                "JournalLine",
                {
                    "journal_id": str(identity),
                    "account_id": line["account"]["resource_id"],
                    "side": line["side"],
                    "amount": line["amount"],
                    "source_record_id": str(record_id),
                    "accounting_binding_id": source["binding"]["resource_id"],
                    "dimension_policy_id": str(policy.policy.resource_id),
                    "dimensions": policy.model_dump(mode="json"),
                },
            )
        )
    nodes = {
        **targets,
        **{
            str(key): {"resource_id": str(key), "object_type": kind, "attributes": attrs}
            for key, kind, attrs in definitions
        },
    }
    try:
        for key, kind, attrs in definitions:
            if kind == "SourceRecord":
                continue
            validate_journal(
                SimpleNamespace(resource_id=key, object_type=kind, attributes=attrs),
                lambda identifier, *_: nodes[str(identifier)],
            )
    except WorkspaceError as exc:
        return {
            "coordinate": coordinate,
            "state": "BLOCKED",
            "blockers": [
                blocker(
                    "SOURCE_CONTEXT_INVALID",
                    "SourceAccountingBinding",
                    exc.detail,
                    **source["binding"],
                )
            ],
        }, None
    mutations = [
        ResourceMutation(
            resource_id=key,
            object_type=kind,
            identity_key="source-posting:" + str(key),
            display_name=f"{coordinate} {kind}",
            attributes=attrs,
            valid_from=request.effective_at,
            evidence_class="SOURCE_BOUND" if kind == "SourceRecord" else "USER_ASSERTED",
        )
        for key, kind, attrs in definitions
    ]
    # Shared proposal validation and checker revalidation enforce these exact heads.
    pins = {UUID(key): UUID(str(node["version_id"])) for key, node in targets.items()}
    proposal = ResourceProposal(
        proposal_id=uuid5(request.request_id, coordinate),
        title=f"Review retained posting {coordinate}",
        rationale=request.rationale,
        access_entity=access_entity,
        mutations=mutations,
        source_versions={item.resource_id: pins for item in mutations},
    )
    return {
        "coordinate": coordinate,
        "state": "CANDIDATE",
        "blockers": [],
        "proposal_id": str(proposal.proposal_id),
    }, proposal


def prepare(principal, request):
    require_permission(principal, "ontology_propose")
    history, plan, resolver = semantic_analysis.load(principal, request.invocation_id)
    if "entity_movement_review" not in history["output"]:
        raise WorkspaceError(
            422, "Journal production requires a retained source-row movement review"
        )
    with resolver.read_session():
        descriptor, _, _ = build(history, plan, resolver, request.company_id)
        targets = {ref["resource_id"]: resolver.version(ref) for ref in plan["static_dependencies"]}
    if descriptor.company.resource_id != request.company_id:
        raise WorkspaceError(404, "Retained source unavailable for this company")
    source = history["output"]["source_document"]
    review = history["output"]["entity_movement_review"]
    coordinates = {pair["source_coordinate"] for pair in review["pairs"]}
    coordinates.update(row["coordinate"] for row in review["reconciliation"]["excluded_rows"])
    if not set(request.coordinates).issubset(coordinates) or not set(request.policies).issubset(
        request.coordinates
    ):
        raise WorkspaceError(422, "Select retained coordinates before supplying side policies")
    record_errors = {}
    for coordinate, policy in request.policies.items():
        if policy.source_record is not None:
            try:
                node = resources.get_resource(principal, policy.source_record.resource_id)[
                    "resource"
                ]
                targets[str(node["resource_id"])] = node
            except WorkspaceError as exc:
                record_errors[coordinate] = blocker(
                    "EXACT_SOURCE_RECORD_REQUIRED",
                    "SourceRecord",
                    exc.detail,
                    **policy.source_record.model_dump(mode="json"),
                )
    rows, proposals = [], {}
    for excluded in review["reconciliation"]["excluded_rows"]:
        rows.append(
            {
                "coordinate": excluded["coordinate"],
                "state": "EXCLUDED",
                "blockers": [
                    blocker(
                        excluded["reason"],
                        "SourceRecord",
                        "A literal posted amount is absent; retain exclusion",
                        evidence=source["evidence"],
                        coordinate=excluded["coordinate"],
                    )
                ],
            }
        )
    for pair in review["pairs"]:
        if pair["source_coordinate"] in record_errors:
            rows.append(
                {
                    "coordinate": pair["source_coordinate"],
                    "state": "BLOCKED",
                    "blockers": [record_errors[pair["source_coordinate"]]],
                }
            )
            continue
        row, proposal = compile_row(pair, source, targets, request, principal.scope.legal_entity_id)
        rows.append(row)
        if proposal is not None:
            # Full existing profile, dimension, period, source, schema and bundle
            # validation; no local replica grants publication eligibility.
            try:
                with resources.resource_connection(principal) as conn:
                    conn.execute(
                        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
                        (f"canonical:{principal.scope.tenant_id}",),
                    )
                    resources._validate(conn, principal, proposal)
                row["state"] = "ELIGIBLE_FOR_REVIEW"
                row["proposal"] = proposal.model_dump(mode="json")
                proposals[row["coordinate"]] = proposal
            except WorkspaceError as exc:
                row.update(
                    state="BLOCKED",
                    blockers=[
                        blocker(
                            "CANONICAL_PUBLICATION_GUARD_REFUSED",
                            "ResourceProposal",
                            exc.detail,
                            proposal_id=str(proposal.proposal_id),
                            required_dependencies=[
                                "SourceAccountingBinding",
                                "PeriodControl",
                                "AccountDimensionPolicy",
                            ],
                        )
                    ],
                )
    manifest = {
        "contract": "source-journal-production/1",
        "invocation_id": str(request.invocation_id),
        "source_sha256": source["sha256"],
        "binding": source["binding"],
        "source_receipt_hash": review["reconciliation"]["receipt_hash"],
        "request": request.model_dump(mode="json"),
        "rows": sorted(rows, key=lambda r: r["coordinate"]),
        "advisory": True,
        "published_journal_count": 0,
    }
    manifest["receipt_hash"] = digest(manifest)
    return manifest, proposals


def submit(principal, request):
    require_permission(principal, "ontology_propose")
    if not request.coordinates:
        raise WorkspaceError(422, "Submission requires an explicit bounded source-row selection")
    from finai_api.services import journal_production_history as retention

    prior = retention.history(principal, request.request_id, request=request)
    if prior is not None:
        return prior
    manifest = retention.history(principal, request.request_id, "PREPARED", request)
    if manifest is None:
        manifest, _ = prepare(principal, request)
        manifest = retention.retain(principal, request, "PREPARED", manifest)
    proposals = {
        row["coordinate"]: ResourceProposal.model_validate(row["proposal"])
        for row in manifest["rows"]
        if "proposal" in row
    }
    submitted = []
    for coordinate in request.coordinates:
        proposal = proposals.get(coordinate)
        if proposal is None:
            continue
        try:
            retained = resources.propose(principal, proposal)
            submitted.append(
                {
                    "coordinate": coordinate,
                    "proposal_id": str(retained.proposal.proposal_id),
                    "decision": retained.decision,
                }
            )
        except WorkspaceError as exc:
            next(row for row in manifest["rows"] if row["coordinate"] == coordinate).update(
                state="BLOCKED",
                blockers=[
                    blocker(
                        "SUBMISSION_REVALIDATION_REFUSED",
                        "ResourceProposal",
                        exc.detail,
                        proposal_id=str(proposal.proposal_id),
                    )
                ],
            )
    manifest["submitted"] = submitted
    manifest["receipt_hash"] = digest({k: v for k, v in manifest.items() if k != "receipt_hash"})
    return retention.retain(principal, request, "SUBMITTED", manifest)


def check(principal, proposal_id, request):
    require_permission(principal, "ontology_review")
    detail = resources.proposal_detail(principal, proposal_id)
    kinds = [item.object_type for item in detail.proposal.mutations]
    if sorted(kinds) not in (
        ["JournalEntry", "JournalLine", "JournalLine", "SourceRecord"],
        ["JournalEntry", "JournalLine", "JournalLine"],
    ):
        raise WorkspaceError(422, "Journal checker requires a complete source-row journal bundle")
    # Shared review rejects same-maker approval and changed dependencies; it is
    # the only operation here that can publish canonical journal versions.
    return resources.review(principal, proposal_id, request)
