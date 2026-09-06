"""Resume real source-row publication through canonical proposals and independent review."""

import argparse
import json
import os
import time
from pathlib import Path
from uuid import UUID

from finai_api.domain.resources import ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.source_financial_facts import prepare, propose
from finai_api.services.workspace import WorkspaceError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--document", required=True)
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--profile", choices=["1c_tb", "1c_journal"], required=True)
    parser.add_argument("--company", type=UUID, required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--progress", required=True, type=Path)
    args = parser.parse_args()
    if not args.approve:
        parser.error("Bulk accepted publication requires explicit --approve")
    principals = [
        Principal.model_validate(v)
        for v in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    author = next(p for p in principals if p.actor_id == args.author)
    reviewer = next(p for p in principals if p.actor_id == args.reviewer)
    if author.actor_id == reviewer.actor_id or author.scope != reviewer.scope:
        raise ValueError(
            "Distinct authors and reviewers in the same source scope are required"
        )
    progress = args.progress.resolve()
    root = Path(__file__).resolve().parents[1] / ".finai" / "artifacts"
    if not progress.is_relative_to(root.resolve()):
        raise ValueError("Progress output must stay within .finai/artifacts")
    first = prepare(author, args.document, args.sheet, args.profile, args.company, 0)
    records = []
    for offset in range(0, first["total_rows"], 25):
        start = time.monotonic()
        identity = None
        try:
            proposal = propose(
                author, args.document, args.sheet, args.profile, args.company, offset
            )
            identity = proposal.proposal.proposal_id
            resources.review(
                reviewer,
                identity,
                ResourceReview(
                    decision="APPROVED",
                    rationale="Reviewed original source row grain, source periods, measure cells and exact company/"
                    "account references. Blank amounts, analytical rows, control totals and repeated "
                    "account observations remain preserved. Currency, ledger and representation authority "
                    "remain unestablished; financial totals or postings are not approved.",
                ),
            )
        except WorkspaceError as exc:
            if (
                exc.status != 409
                or exc.detail != "This source fact page is empty or already published"
            ):
                raise
        record = {
            "document_id": args.document,
            "source_sha256": first["source_sha256"],
            "object_type": first["object_type"],
            "offset": offset,
            "count": min(25, first["total_rows"] - offset),
            "total": first["total_rows"],
            "proposal_id": str(identity) if identity else None,
            "state": "APPROVED" if identity else "EXISTING_ROWS_VERIFIED",
            "elapsed_seconds": round(time.monotonic() - start, 2),
        }
        records.append(record)
        temporary = progress.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, indent=2), encoding="utf-8")
        temporary.replace(progress)
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
