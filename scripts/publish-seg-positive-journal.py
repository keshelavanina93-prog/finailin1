"""Smallest authentic reviewed SEG publication and repeatable reconciliation readback.

Requires prepared compatibility/account policies. --apply submits and reviews only
Base!S2; --readback reopens its persisted intent. Amounts are never supplied by this script.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from fastapi import HTTPException
from finai_api.domain.journal_production import JournalProductionRequest
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import (
    company_journals,
    journal_production,
    journal_production_history,
    journal_reconciliation,
    period_control,
    resources,
    semantic_analysis,
)
from finai_api.services.journal_dimensions import policy_identity
from finai_api.services.workspace import WorkspaceError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--readback", action="store_true")
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    grants = [
        Principal.model_validate(v)
        for v in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    maker = next(
        p
        for p in grants
        if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
    )
    checker = next(
        p
        for p in grants
        if p.actor_id != maker.actor_id
        and p.scope == maker.scope
        and {"ontology_admin", "ontology_review"} <= set(p.permissions)
    )
    invocation = UUID("60703b36-2243-568f-804b-c622b6365fc4")
    history, _plan, _resolver = semantic_analysis.load(maker, invocation)
    source = history["output"]["source_document"]
    row = next(r for r in history["output"]["source_rows"] if r["row"] == 2)
    compatibility_id = uuid5(
        UUID(source["binding"]["resource_id"]), "source-journal-compatibility/1"
    )
    compatibility = resources.get_resource(maker, compatibility_id)["resource"]
    reason = "NIN-44 reviewed authentic SEG Base!S2 only; preserve 731.97 GEL as posted and original side-specific analytics."
    if args.request_file.exists():
        request = JournalProductionRequest.model_validate_json(
            args.request_file.read_text(encoding="utf-8")
        )
    else:
        policies = {}
        for side, account_field, columns in (
            ("debit", "account_code", ["F", "G"]),
            ("credit", "credit_account_code", ["M", "N"]),
        ):
            account = source["accounts"][row["attributes"][account_field]]
            identity, _ = policy_identity(maker.scope.tenant_id, account["resource_id"])
            policy = resources.get_resource(maker, identity)["resource"]
            rules = policy["attributes"]["definition"]["rules"]
            assert len(rules) == len(columns) == 2
            assignments = []
            # Source chart ordering is retained in this policy candidate. Each
            # reviewed user assertion names the exact original cell and label.
            for rule_ref, column in zip(rules, columns, strict=True):
                rule = resources.get_resource(maker, UUID(rule_ref["resource_id"]))[
                    "resource"
                ]
                assert rule["version_id"] == rule_ref["version_id"]
                dimension_id = UUID(rule["attributes"]["dimension_id"])
                cell = f"Base!{column}2"
                value = row["cells"][cell]["value"]
                assert (
                    isinstance(value, str)
                    and value.strip()
                    and not row["cells"][cell]["formula"]
                )
                member_id = uuid5(dimension_id, value)
                current = resources.current_resources(maker, [member_id]).get(
                    str(member_id)
                )
                if current is None:
                    if not args.apply:
                        raise WorkspaceError(
                            409, "Source-backed dimension members require review"
                        )
                    proposal = ResourceProposal(
                        title="Review original SEG analytical member",
                        rationale=reason,
                        access_entity=maker.scope.legal_entity_id,
                        mutations=[
                            ResourceMutation(
                                resource_id=member_id,
                                object_type="DimensionMember",
                                identity_key="seg-member:" + str(member_id),
                                display_name=value[:200],
                                attributes={
                                    "dimension_id": str(dimension_id),
                                    "code": value,
                                    "evidence_id": source["evidence"]["resource_id"],
                                },
                                valid_from=datetime.now(UTC),
                            )
                        ],
                    )
                    resources.propose(maker, proposal)
                    resources.review(
                        checker,
                        proposal.proposal_id,
                        ResourceReview(decision="APPROVED", rationale=reason),
                    )
                    current = resources.get_resource(maker, member_id)["resource"]
                assignments.append(
                    {
                        "member": {
                            "resource_id": str(member_id),
                            "version_id": current["version_id"],
                        },
                        "provenance": {
                            "kind": "USER_ASSERTED",
                            "reason": f"Reviewed {side} chart analytic from retained {cell}: {value}",
                        },
                    }
                )
            policies[side] = {
                "contract": "journal-line-dimensions/1",
                "policy": {
                    "resource_id": str(identity),
                    "version_id": policy["version_id"],
                },
                "assignments": assignments,
            }
        request = JournalProductionRequest(
            request_id=uuid5(invocation, "positive-Base-S2/1"),
            invocation_id=invocation,
            company_id=UUID(source["company_id"]),
            effective_at=datetime.now(UTC),
            rationale=reason,
            coordinates=["Base!S2"],
            compatibility={
                "resource_id": compatibility_id,
                "version_id": compatibility["version_id"],
            },
            policies={"Base!S2": policies},
        )
        args.request_file.write_text(
            request.model_dump_json(indent=2), encoding="utf-8"
        )
    context = source["context"]
    ids = [
        UUID(source["company_id"]),
        *[UUID(context[k]) for k in ("ledger_id", "book_id", "period_id")],
    ]
    if args.apply:
        selected = company_journals.selection(maker, *ids, datetime.now(UTC))
        control_id, _ = period_control.identity(
            maker.scope.tenant_id, {k: v["resource_id"] for k, v in selected.items()}
        )
        control = resources.current_resources(maker, [control_id]).get(str(control_id))
        if control is None:
            proposal_id = uuid5(request.request_id, "period-control")
            period_control.propose(
                maker,
                period_control.ProposalRequest(
                    request_id=proposal_id,
                    selection=selected,
                    expected_version_id=None,
                    state="OPEN",
                    reason=reason,
                ),
            )
            resources.review(
                checker,
                proposal_id,
                ResourceReview(decision="APPROVED", rationale=reason),
            )
        elif control["attributes"]["definition"]["state"] != "OPEN":
            raise WorkspaceError(
                409, "Existing locked period requires a separate business decision"
            )
    preview = journal_production_history.history(
        maker, request.request_id, "PREPARED", request
    )
    if preview is None:
        preview, _ = journal_production.prepare(maker, request)
    selected_row = next(r for r in preview["rows"] if r["coordinate"] == "Base!S2")
    output = {"preview": selected_row, "request": request.model_dump(mode="json")}
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.apply:
        submitted = journal_production.submit(maker, request)
        assert submitted["submitted"], selected_row
        proposal_id = UUID(submitted["submitted"][0]["proposal_id"])
        try:
            journal_production.check(
                maker,
                proposal_id,
                ResourceReview(decision="APPROVED", rationale=reason),
            )
            raise AssertionError("Maker approved own journal")
        except WorkspaceError as exc:
            assert exc.status == 403
            output["maker_denied"] = True
        except HTTPException as exc:
            assert exc.status_code == 403
            output["maker_denied"] = True
        accepted = journal_production.check(
            checker, proposal_id, ResourceReview(decision="APPROVED", rationale=reason)
        )
        output["decision"] = accepted.decision
    if args.apply or args.readback:
        output["attempt"] = journal_production_history.history(
            maker, request.request_id
        )
        reconciled = journal_reconciliation.reconcile(
            maker, invocation, request.company_id
        )
        output["reconciliation"] = reconciled["reconciliation"]
        output["source_projection"] = reconciled["source_projection"].model_dump(
            mode="json"
        )
        accepted = [
            r
            for r in output["reconciliation"]["accepted"]
            if r["source_coordinate"] == "Base!S2"
        ]
        assert len(accepted) == 1
        journal = accepted[0]["journal"]
        detail = company_journals.detail(
            maker, *ids, UUID(journal["resource_id"]), UUID(journal["version_id"])
        )
        assert len(detail["lines"]) == 2
        assert {
            r["line"]["attributes"]["amount"]["amount"] for r in detail["lines"]
        } == {"731.97"}
        assert all(r["dimensions"]["state"] == "COMPLETE" for r in detail["lines"])
        output["journal_detail"] = detail
        retry = journal_production.submit(maker, request)
        assert retry == output["attempt"]
        output["retry_same_receipt"] = True
        assert output["reconciliation"]["excluded_rows"] == [
            {
                "row": 288,
                "reason": "MISSING_LITERAL_POSTED_AMOUNT",
                "coordinate": "Base!S288",
            }
        ]
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "row_state": selected_row["state"],
                "decision": output.get("decision"),
                "accepted": len(output.get("reconciliation", {}).get("accepted", [])),
            }
        )
    )


if __name__ == "__main__":
    main()
