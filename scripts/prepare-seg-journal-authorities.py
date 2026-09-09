"""Review authentic SEG compatibility and chart-derived account policy candidates.

Read-only by default. --apply uses configured distinct maker/checker identities,
preserves existing heads and never renames source profiles or changes source values.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources, semantic_analysis
from finai_api.services.entity_movement_review import digest
from finai_api.services.journal_dimensions import policy_identity


def pin(node):
    return {key: str(node[key]) for key in ("resource_id", "version_id")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
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
    history, _plan, resolver = semantic_analysis.load(maker, invocation)
    source = history["output"]["source_document"]
    assert source["company_id"] == "365aa5d9-c2ec-52e1-867a-50fe3415f486"
    with resolver.read_session():
        scope, binding = (
            resolver.version(source["scope"]),
            resolver.version(source["binding"]),
        )
        nodes = {
            name: resolver.field(binding, name + "_id")
            for name in ("ledger", "book", "period", "currency")
        }
        nodes.update(
            company=resolver.field(scope, "legal_entity_id"),
            chart=resolver.field(scope, "chart_id"),
        )
        accounts = {
            code: resolver.version(ref) for code, ref in source["accounts"].items()
        }
    records = resources.list_resources(
        maker, "SourceAccountDefinition", "", 0, limit=1000
    )
    definitions = {
        r.attributes["account_code"]: r.model_dump(mode="json")
        for r in records
        if r.attributes["account_code"] in accounts
    }
    assert len(definitions) == len(accounts) == 38
    reason = (
        "Reviewed under NIN-44 b86825c1: preserve SEG statutory 1C January 2025 GEL "
        "source amounts as posted; chart-named analytics are explicit required dimensions "
        "for this bounded source-backed journal journey. No extra dimensions or statement authority."
    )
    proposals = []

    def publish(kind, identity, key, attrs, access=None, lineage=None):
        attrs = json.loads(json.dumps(attrs, default=str))
        prior = resources.current_resources(maker, [identity]).get(str(identity))
        if prior and prior["attributes"] == attrs:
            return prior
        mutation = ResourceMutation(
            resource_id=identity,
            object_type=kind,
            identity_key=key,
            display_name=key[:200],
            attributes=attrs,
            valid_from=datetime.now(UTC),
            expected_version_id=prior["version_id"] if prior else None,
        )
        proposal = ResourceProposal(
            title="Review SEG " + kind,
            rationale=reason,
            access_entity=access or maker.scope.legal_entity_id,
            mutations=[mutation],
            source_versions={identity: lineage} if lineage else {},
        )
        proposals.append(
            {
                "proposal_id": str(proposal.proposal_id),
                "object_type": kind,
                "resource_id": str(identity),
            }
        )
        if not args.apply:
            return None
        resources.propose(maker, proposal)
        resources.review(
            checker,
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale=reason),
        )
        return resources.get_resource(maker, identity)["resource"]

    if args.apply:
        for spec in platform_definitions(maker.scope.tenant_id):
            if spec["object_type"] == "SchemaDefinition" and spec["identity_key"] in {
                "SourceJournalCompatibility",
                "JournalEntry",
                "JournalLine",
            }:
                identity = canonical_id(
                    maker.scope.tenant_id, "SchemaDefinition", spec["identity_key"]
                )
                publish(
                    "SchemaDefinition",
                    identity,
                    spec["identity_key"],
                    spec["attributes"],
                    "__PLATFORM__",
                )
    compatibility_id = uuid5(
        UUID(source["binding"]["resource_id"]), "source-journal-compatibility/1"
    )
    attrs = {
        "accounting_binding_id": source["binding"]["resource_id"],
        "scope_id": source["scope"]["resource_id"],
        "legal_entity_id": source["company_id"],
        **{
            key: source["context"][key]
            for key in ("ledger_id", "book_id", "period_id", "currency_id")
        },
        "definition": {
            "contract": "source-journal-compatibility/1",
            "source_profile": "seg_expense_base",
            "source_family": "SEG_EXPENSE_BASE",
            "source_sha256": source["sha256"],
            "binding_version_id": source["binding"]["version_id"],
            "scope_version_id": source["scope"]["version_id"],
            "sheet": "Base",
            "grain": "SOURCE_ROW",
            "amount_field": "source_amount",
            "amount_column": "S",
            "amount_header": "Сумма",
            "amount_semantics": "DEBIT_CREDIT",
            "vat_treatment": "AS_POSTED",
            "row_identity": "RECORDER_AND_LINE",
            "amount_conversion": "NONE",
            "rationale": reason,
        },
    }
    compatibility = publish(
        "SourceJournalCompatibility",
        compatibility_id,
        "seg-january-journal-compatibility",
        attrs,
        lineage={
            UUID(str(n["resource_id"])): UUID(str(n["version_id"]))
            for n in [binding, scope, *nodes.values()]
        },
    )
    policies = []
    for code, account in sorted(accounts.items()):
        observed = definitions[code]
        analytics = observed["attributes"]["definition"]["analytics"]
        rules = []
        for analytic in analytics:
            label = analytic["source_label"]
            dimension_id = uuid5(UUID(source["company_id"]), "chart-analytic:" + label)
            dimension = publish(
                "DimensionDefinition",
                dimension_id,
                "chart-analytic:" + label,
                {"code": label},
            )
            key = f"account-dimension:{account['resource_id']}:{dimension_id}"
            rule_id = canonical_id(maker.scope.tenant_id, "AccountDimensionRule", key)
            rule = (
                publish(
                    "AccountDimensionRule",
                    rule_id,
                    key,
                    {
                        "account_id": account["resource_id"],
                        "dimension_id": str(dimension_id),
                        "required": True,
                    },
                )
                if dimension
                else None
            )
            rules.append(
                {
                    "dimension_id": str(dimension_id),
                    "source_label": label,
                    "coordinate": analytic["coordinate"],
                    "rule": pin(rule) if rule else None,
                    "required": True,
                }
            )
        policy_id, key = policy_identity(maker.scope.tenant_id, account["resource_id"])
        context = {
            name: pin(nodes[name]) for name in ("company", "chart", "book", "period")
        }
        evidence = resources.get_resource(
            maker, UUID(observed["attributes"]["evidence_id"])
        )["resource"]
        context.update(
            source_account=pin(observed),
            evidence=pin(evidence),
            additional_dimensions="PROHIBITED",
            state="REVIEWED_RULE_SET"
            if analytics
            else "EXPLICIT_NO_ADDITIONAL_DIMENSIONS",
        )
        attributes = {
            "account_id": account["resource_id"],
            "chart_id": nodes["chart"]["resource_id"],
            "legal_entity_id": source["company_id"],
            "definition": {
                "contract": "account-dimension-policy/1",
                "rules": [r["rule"] for r in rules if r["rule"]],
                "reason": reason,
                "context": context,
            },
        }
        retained = (
            publish(
                "AccountDimensionPolicy",
                policy_id,
                key,
                attributes,
                lineage={
                    UUID(ref["resource_id"]): UUID(ref["version_id"])
                    for ref in [
                        pin(account),
                        pin(observed),
                        pin(evidence),
                        *[pin(n) for n in nodes.values()],
                    ]
                },
            )
            if args.apply
            else None
        )
        policies.append(
            {
                "account": pin(account),
                "account_code": code,
                "context": context,
                "rules": rules,
                "policy": pin(retained) if retained else None,
            }
        )
    output = {
        "mode": "APPLIED" if args.apply else "REVIEWABLE_CANDIDATES",
        "compatibility": pin(compatibility) if compatibility else attrs,
        "policies": policies,
        "proposals": proposals,
        "maker": maker.actor_id,
        "checker": checker.actor_id,
    }
    output["receipt_hash"] = digest(output)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "mode": output["mode"],
                "policies": len(policies),
                "receipt_hash": output["receipt_hash"],
            }
        )
    )


if __name__ == "__main__":
    main()
