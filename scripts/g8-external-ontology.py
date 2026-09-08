"""Local operator CLI for retained ontology preparation and exact release inspection."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from finai_api.domain.external_ontology import (
    ImportRequest,
    ReleaseInspectionRequest,
    SourceDefinition,
    TermInspectionRequest,
)
from finai_api.domain.ontology_validation import (
    ConstraintProfileDefinition,
    OntologyProfileDefinition,
    ValidationRunRequest,
)

COMMANDS = {
    "propose-source": ("/external/sources/proposals", SourceDefinition),
    "prepare-import": ("/external/imports/proposals", ImportRequest),
    "inspect-release": ("/external/releases/inspect", ReleaseInspectionRequest),
    "rebuild-index": ("/external/index/rebuild", ReleaseInspectionRequest),
    "inspect-term": ("/external/terms/inspect", TermInspectionRequest),
    "propose-profile": ("/external/profiles/proposals", OntologyProfileDefinition),
    "propose-constraints": ("/external/constraint-profiles/proposals", ConstraintProfileDefinition),
    "validate": ("/external/validation/runs", ValidationRunRequest),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["retain", "validation-status", "propose-report", *COMMANDS])
    parser.add_argument("file", type=Path, help="RDF bytes for retain, JSON request otherwise")
    parser.add_argument("--base-url", default="http://127.0.0.1:8062/v1/ontology")
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if (
        url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username or url.password or url.query or url.fragment
    ):
        parser.error("This CLI requires an explicit local HTTP runtime without URL credentials")
    token = os.environ.get("G8_ONTOLOGY_TOKEN")
    if not token:
        parser.error("Set G8_ONTOLOGY_TOKEN to the intended existing operator credential")
    budget = 8 * 1024 * 1024 if args.command == "retain" else 256 * 1024
    with args.file.open("rb") as source:
        content = source.read(budget + 1)
    if not content or len(content) > budget:
        parser.error("Input is empty or exceeds this command's byte budget")
    base = args.base_url.rstrip("/")
    with httpx.Client(
        headers={"Authorization": "Bearer " + token}, timeout=45, follow_redirects=False
    ) as client:
        if args.command == "retain":
            response = client.post(
                base + "/source-documents", params={"filename": args.file.name}, content=content
            )
        elif args.command in {"validation-status", "propose-report"}:
            reference = json.loads(content)
            if not isinstance(reference, dict) or set(reference) != {"request_id"}:
                parser.error("Validation lookup requires exactly one request_id")
            identity = UUID(reference["request_id"])
            endpoint = base + f"/external/validation/runs/{identity}"
            response = (
                client.get(endpoint) if args.command == "validation-status"
                else client.post(endpoint + "/report-proposals")
            )
        else:
            suffix, model = COMMANDS[args.command]
            request = model.model_validate_json(content)
            response = client.post(base + suffix, json=request.model_dump(mode="json"))
    if not response.is_success:
        # Never include client headers or credentials in diagnostics.
        parser.exit(1, f"G8 rejected {args.command}: HTTP {response.status_code}\n")
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
