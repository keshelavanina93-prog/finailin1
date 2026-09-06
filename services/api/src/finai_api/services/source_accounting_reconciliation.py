"""Retained source-structure comparisons, without promoting a financial representation."""

from collections import Counter, defaultdict
from decimal import Decimal, Inexact, localcontext
from itertools import combinations
from uuid import UUID

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.fact_runs import retain_run
from finai_api.services.source_documents import document_bytes
from finai_api.services.source_financial_facts import read_rows
from finai_api.services.workspace import WorkspaceError
from finai_api.services.xls_source import FIELDS


def reconcile_structure(parsed: dict) -> dict:
    rows = parsed["rows"]
    by_key = {row["attributes"]["source_row_key"]: row for row in rows}
    children = defaultdict(list)
    accounts = defaultdict(list)
    for row in rows:
        attrs = row["attributes"]
        if attrs.get("parent_source_row_key"):
            children[attrs["parent_source_row_key"]].append(row)
        if row.get("account_code"):
            accounts[row["account_code"]].append(row)
    duplicate_accounts = []
    controls = []
    with localcontext() as context:
        context.prec = 50
        context.traps[Inexact] = True
        for code, members in sorted(accounts.items()):
            if len(members) < 2:
                continue
            if len(members) > 100:
                raise WorkspaceError(422, "Repeated-account comparison exceeds 100 source rows")
            comparisons = []
            for left, right in combinations(members, 2):
                a, b = left["attributes"], right["attributes"]
                measures = {}
                for name in FIELDS:
                    x, y = a.get(name), b.get(name)
                    measures[name] = {
                        "left": x,
                        "right": y,
                        "state": "ABSENT_BOTH"
                        if x is None and y is None
                        else (
                            "INCOMPLETE"
                            if x is None or y is None
                            else ("EQUAL" if Decimal(x) == Decimal(y) else "DIFFERENT")
                        ),
                        "difference": None
                        if x is None or y is None
                        else format(Decimal(x) - Decimal(y), "f"),
                    }
                ancestor = b.get("parent_source_row_key")
                visited = set()
                while ancestor and ancestor not in visited and ancestor != a["source_row_key"]:
                    visited.add(ancestor)
                    ancestor = (
                        by_key.get(ancestor, {}).get("attributes", {}).get("parent_source_row_key")
                    )
                comparisons.append(
                    {
                        "left_row": a["source_row_key"],
                        "right_row": b["source_row_key"],
                        "outline_relation": "ANCESTOR_DESCENDANT"
                        if ancestor == a["source_row_key"]
                        else "SEPARATE_BRANCHES",
                        "measure_state": "SAME_OBSERVED_MEASURES"
                        if all(m["state"] in {"EQUAL", "ABSENT_BOTH"} for m in measures.values())
                        else "DIFFERENT_OBSERVED_MEASURES",
                        "measures": measures,
                    }
                )
            duplicate_accounts.append({"account_code": code, "comparisons": comparisons})
        for parent_key, members in children.items():
            parent = by_key[parent_key]["attributes"]
            for name in FIELDS:
                observed = parent.get(name)
                present = [r for r in members if name in r["attributes"]]
                if observed is None and not present:
                    continue
                missing = [
                    r["attributes"]["source_row_key"]
                    for r in members
                    if name not in r["attributes"]
                ]
                complete = observed is not None and not missing
                subtotal = sum((Decimal(r["attributes"][name]) for r in present), Decimal(0))
                delta = Decimal(observed) - subtotal if complete else None
                controls.append(
                    {
                        "parent_row": parent_key,
                        "measure": name,
                        "parent_value": observed,
                        "child_rows": [r["attributes"]["source_row_key"] for r in members],
                        "missing_child_rows": missing,
                        "present_children": len(present),
                        "total_children": len(members),
                        "children_value": format(subtotal, "f") if complete else None,
                        "difference": format(delta, "f") if delta is not None else None,
                        "state": "INCOMPLETE"
                        if not complete
                        else ("OBSERVED_AGREEMENT" if delta == 0 else "OBSERVED_DIFFERENCE"),
                    }
                )
    # Recorder/document alone is not a journal-line identity. Retain every row;
    # repeated documents are expected in multi-line source documents.
    documents = defaultdict(list)
    if parsed["object_type"] == "SourceJournalMovement":
        for row in rows:
            a = row["attributes"]
            documents[(a["posting_date"], a["document_reference"])].append(a["source_row_key"])
    return {
        "object_type": parsed["object_type"],
        "input_count": len(rows),
        "row_roles": dict(
            Counter(r["attributes"].get("source_row_role", "JOURNAL_MOVEMENT") for r in rows)
        ),
        "repeated_accounts": duplicate_accounts,
        "hierarchy_measure_comparisons": controls,
        "comparison_counts": dict(Counter(c["state"] for c in controls)),
        "multirow_documents": [
            {"posting_date": key[0], "document_reference": key[1], "source_rows": value}
            for key, value in sorted(documents.items())
            if len(value) > 1
        ],
        "state": "REVIEW_REQUIRED",
        "authority": "SOURCE_STRUCTURE_COMPARISON",
        "financial_certification": None,
        "limitations": [
            "Outline ancestry is source presentation, not an approved additive "
            "accounting hierarchy.",
            "Equal observed measures do not establish duplicate economic events "
            "or select authority.",
            "Blank measures stay missing; incomplete comparisons do not assume zero.",
            "Company ledger, currency, analytical grain and representation selection "
            "remain unestablished.",
        ],
    }


def assess(principal: Principal, document_id: str, sheet: str, profile: str, company_id: UUID):
    metadata, content = document_bytes(principal, document_id)
    parsed = read_rows(content, sheet, profile)
    evidence_id = canonical_id(
        principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"]
    )
    heads = resources.current_resources(principal, [company_id, evidence_id])
    company, evidence = heads.get(str(company_id)), heads.get(str(evidence_id))
    if (
        not company
        or not evidence
        or any(
            head["authority_state"] != "APPROVED" or head["evidence_class"] != "SOURCE_BOUND"
            for head in (company, evidence)
        )
        or company["object_type"] != "LegalEntity"
        or (
            company["attributes"].get("evidence_id") != str(evidence_id)
            or company["display_name"] != parsed["company_label"]
        )
    ):
        raise WorkspaceError(409, "Select the reviewed company and evidence from this source")
    return retain_run(
        principal,
        {
            **reconcile_structure(parsed),
            "source_document_id": document_id,
            "source_sha256": metadata["source_sha256"],
            "worksheet": sheet,
            "profile": profile,
            "source_parser": "source-accounting/1",
            "comparison_runtime": "source-structure/1",
            "input_stage": "RETAINED_ORIGINAL_SOURCE",
            "inputs": [
                {"resource_id": h["resource_id"], "version_id": h["version_id"]}
                for h in (company, evidence)
            ],
        },
    )
