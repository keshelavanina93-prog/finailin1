"""Prepare exact retained OGC vocabulary through independent review checkpoints.

No publisher retrieval, review decision, runtime launch or company fact creation.
The default is a local preview. Every API mutation requires --apply.
"""

import argparse
import json
import os
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from finai_api.domain.external_ontology import ImportRequest, RetainedDocument, SourceDefinition
from finai_api.domain.ontology_validation import OntologyProfileDefinition
from finai_api.domain.semantic_analysis import Pin

MANIFEST = Path(__file__).resolve().parents[1] / (
    "docs/external-profiles/geosparql-1.1-vocabulary.json"
)
RECEIPT = "g8-geosparql-retention/1"


def local_path(path: Path) -> Path:
    resolved = path.resolve()
    if os.name == "nt" and resolved.drive.upper() != "D:":
        raise ValueError("Local preparation inputs and outputs must remain on D:")
    return resolved


def read_bounded(path: Path, maximum: int = 256_000) -> bytes:
    with local_path(path).open("rb") as stream:
        data = stream.read(maximum + 1)
    if not data or len(data) > maximum:
        raise ValueError("Empty input or preparation byte budget exceeded")
    return data


def read_json(path: Path) -> Any:
    return json.loads(read_bounded(path))


def aware_time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Retrieval time requires an explicit timezone")
    return stamp


def verify_artifacts(directory: Path) -> tuple[dict, str, dict[str, bytes], dict]:
    directory = local_path(directory)
    manifest_bytes = read_bounded(MANIFEST)
    manifest = json.loads(manifest_bytes)
    retrieval = read_json(directory / "retrieval-manifest.json")
    if not isinstance(retrieval, list):
        raise ValueError("Retrieval manifest must contain an artifact list")
    contents, provenance = {}, {}
    for artifact in manifest["artifacts"]:
        name = artifact["file"]
        path = local_path(directory / name)
        if not path.is_relative_to(directory):
            raise ValueError("Artifact path escapes the supplied directory")
        data = read_bounded(path, artifact["byte_length"])
        if len(data) != artifact["byte_length"] or sha256(data).hexdigest() != artifact["sha256"]:
            raise ValueError(f"Original artifact hash or byte length differs: {name}")
        text = data.decode("utf-8")
        for marker in (
            "<" + artifact["artifact_iri"] + ">",
            "schema:publisher <" + manifest["publisher_iri"] + ">",
            "schema:license <" + manifest["declared_license_iri"] + ">",
            manifest["version_info_prefix"],
            artifact["version_iri_turtle"],
        ):
            if marker not in text:
                raise ValueError(f"Original publisher/license/version metadata differs: {name}")
        matches = [
            entry for entry in retrieval if isinstance(entry, dict) and entry.get("file") == name
        ]
        if len(matches) != 1:
            raise ValueError(f"Exactly one retrieval record is required: {name}")
        record = matches[0]
        expected = {
            "sha256": artifact["sha256"],
            "byte_length": artifact["byte_length"],
            "requested_url": artifact["source_url"],
            "retrieved_url": artifact["source_url"],
        }
        if any(record.get(key) != value for key, value in expected.items()):
            raise ValueError(f"Retrieval provenance differs from pinned upstream artifact: {name}")
        aware_time(record["retrieved_at"])
        if not record.get("retrieval_time_basis", "").strip():
            raise ValueError(f"Retrieval time basis is required: {name}")
        contents[name], provenance[name] = (
            data,
            {
                "retrieved_at": record["retrieved_at"],
                "retrieval_time_basis": record["retrieval_time_basis"],
            },
        )
    canonical_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return manifest, sha256(canonical_manifest).hexdigest(), contents, provenance


def publisher_definition(manifest: dict) -> SourceDefinition:
    return SourceDefinition(
        publisher=manifest["publisher"],
        source_url=manifest["publisher_iri"],
        namespaces=[
            namespace for item in manifest["artifacts"] for namespace in item["owned_namespaces"]
        ],
        license=manifest["declared_license_iri"],
        supported_formats=["TURTLE"],
    )


def read_pin(path: Path | None) -> Pin:
    if path is None:
        raise ValueError("An explicit reviewed resource/version/content-hash pin file is required")
    return Pin.model_validate(read_json(path))


def retrieval_times(values: list[str], provenance: dict) -> dict[str, str]:
    result = {}
    for value in values:
        name, separator, stamp = value.partition("=")
        if not separator or name not in provenance or name in result:
            raise ValueError("Use one --retrieved-at filename=aware-time per selected artifact")
        if aware_time(stamp) != aware_time(provenance[name]["retrieved_at"]):
            raise ValueError("Explicit retrieval time differs from retained retrieval evidence")
        result[name] = stamp
    if set(result) != set(provenance):
        raise ValueError("Every selected artifact requires its explicit --retrieved-at")
    return result


def import_request(
    manifest: dict, digest: str, provenance: dict, args: argparse.Namespace
) -> ImportRequest:
    source = read_pin(args.source_pin)
    if args.retained is None:
        raise ValueError("Release preparation requires the retained document receipt")
    receipt = read_json(args.retained)
    names = {item["file"] for item in manifest["artifacts"]}
    if (
        receipt.get("contract") != RECEIPT
        or receipt.get("manifest_sha256") != digest
        or set(receipt.get("documents", {})) != names
        or receipt.get("retrieval") != provenance
    ):
        raise ValueError(
            "Retention receipt differs from this exact manifest and retrieval evidence"
        )
    times = retrieval_times(args.retrieved_at, provenance)
    modules = []
    for item in manifest["artifacts"]:
        document = RetainedDocument.model_validate(receipt["documents"][item["file"]])
        if document.sha256 != item["sha256"] or document.byte_length != item["byte_length"]:
            raise ValueError("Retained document receipt differs from original bytes")
        modules.append(
            {
                "source": source,
                "document": document,
                "retrieved_at": times[item["file"]],
                "license": manifest["declared_license_iri"],
                **{
                    key: item[key]
                    for key in (
                        "artifact_iri",
                        "format",
                        "owned_namespaces",
                        "permitted_import_iris",
                        "source_url",
                    )
                },
            }
        )
    return ImportRequest.model_validate(
        {
            "source": source,
            "release_label": manifest["release_label"],
            "publication_status": manifest["publication_status"],
            "modules": modules,
        }
    )


def api(client: Any, method: str, path: str, **kwargs: Any) -> dict:
    response = client.request(method, path, **kwargs)
    if not response.is_success:
        raise ValueError(
            f"G8 refused preparation: HTTP {response.status_code}; no approval performed"
        )
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("Unexpected G8 response contract")
    return value


def verify_publisher(client: Any, source: Pin, manifest: dict) -> None:
    detail = api(client, "GET", f"resources/{source.resource_id}")
    versions = [
        row
        for row in detail["versions"]
        if (
            str(row["resource_id"]) == str(source.resource_id)
            and str(row["version_id"]) == str(source.version_id)
            and row["content_hash"] == source.content_hash
        )
    ]
    if len(versions) != 1 or (
        versions[0]["object_type"] != "ExternalOntologySource"
        or versions[0]["authority_state"] != "APPROVED"
        or SourceDefinition.model_validate(versions[0]["attributes"]["definition"])
        != publisher_definition(manifest)
    ):
        raise ValueError(
            "Reviewed publisher pin differs from the declared OGC vocabulary publisher"
        )
    # Current-effective/lifecycle checks remain inside the canonical import/profile services.


def verify_release(client: Any, pin: Pin, manifest: dict, provenance: dict) -> None:
    detail = api(
        client,
        "POST",
        "external/releases/inspect",
        json={
            "release": pin.model_dump(mode="json"),
            "mode": "CURRENT_RELEASE",
        },
    )
    if (
        detail.get("release") != pin.model_dump(mode="json")
        or detail.get("mode") != "CURRENT_RELEASE"
    ):
        raise ValueError("Release inspection differs from the requested exact pin")
    request = ImportRequest.model_validate(detail["definition"]["request"])
    if (
        request.release_label != manifest["release_label"]
        or request.publication_status != "DEVELOPMENT"
    ):
        raise ValueError("Reviewed release is not this vocabulary preparation")
    expected = {item["artifact_iri"]: item for item in manifest["artifacts"]}
    if {module.artifact_iri for module in request.modules} != set(expected):
        raise ValueError("Reviewed release graphs differ from the vocabulary selection")
    for module in request.modules:
        item = expected[module.artifact_iri]
        if (
            module.source != request.source
            or module.document.sha256 != item["sha256"]
            or module.document.byte_length != item["byte_length"]
            or module.owned_namespaces != item["owned_namespaces"]
            or module.permitted_import_iris
            or module.source_url != item["source_url"]
            or module.license != manifest["declared_license_iri"]
            or module.format != "TURTLE"
            or module.retrieved_at != aware_time(provenance[item["file"]]["retrieved_at"])
        ):
            raise ValueError("Reviewed release module differs from exact retained OGC provenance")
    verify_publisher(client, request.source, manifest)


def run(args: argparse.Namespace, client: Any = None) -> dict:
    manifest, digest, contents, provenance = verify_artifacts(args.artifact_dir)
    envelope = {"stage": args.stage, "manifest_sha256": digest, "review_performed": False}
    if args.stage == "verify":
        return {
            **envelope,
            "state": "LOCAL_ARTIFACT_VERIFIED",
            "retrieval": provenance,
            "metadata_version": manifest["metadata_version"],
            "artifacts": manifest["artifacts"],
        }
    if args.stage == "publisher":
        request = publisher_definition(manifest)
        endpoint = "external/sources/proposals"
    elif args.stage == "retain":
        if not args.apply:
            return {
                **envelope,
                "state": "PREVIEW_ONLY",
                "files": list(contents),
                "retrieval": provenance,
            }
        documents = {}
        for item in manifest["artifacts"]:
            response = api(
                client,
                "POST",
                "source-documents",
                params={"filename": item["file"]},
                content=contents[item["file"]],
            )
            document = RetainedDocument.model_validate(
                {key: response[key] for key in ("document_id", "sha256", "byte_length")}
            )
            if document.sha256 != item["sha256"] or document.byte_length != item["byte_length"]:
                raise ValueError("Runtime retention receipt differs from submitted original bytes")
            documents[item["file"]] = document.model_dump(mode="json")
        return {
            **envelope,
            "contract": RECEIPT,
            "state": "RETAINED_UNINTERPRETED",
            "documents": documents,
            "retrieval": provenance,
        }
    elif args.stage == "release":
        request = import_request(manifest, digest, provenance, args)
        endpoint = "external/imports/proposals"
        if args.apply:
            verify_publisher(client, request.source, manifest)
    else:
        release = read_pin(args.release_pin)
        request = OntologyProfileDefinition.model_validate(
            {
                "purpose": manifest["purpose"],
                "domain_pack": manifest["profile_key"],
                "members": [
                    {
                        "release": release,
                        "graph_iris": [item["artifact_iri"] for item in manifest["artifacts"]],
                    }
                ],
            }
        )
        endpoint = "external/profiles/proposals"
        if args.apply:
            verify_release(client, release, manifest, provenance)
    payload = request.model_dump(mode="json")
    if not args.apply:
        return {**envelope, "state": "PREVIEW_ONLY", "request": payload}
    return {
        **envelope,
        "state": "RUNTIME_RESPONSE",
        "response": api(client, "POST", endpoint, json=payload),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("stage", choices=("verify", "publisher", "retain", "release", "profile"))
    result.add_argument("--artifact-dir", type=Path, required=True)
    result.add_argument(
        "--apply",
        action="store_true",
        help="Prepare using the existing local operator; never approve",
    )
    result.add_argument("--base-url", default="http://127.0.0.1:8062/v1/ontology/")
    result.add_argument("--source-pin", type=Path)
    result.add_argument("--release-pin", type=Path)
    result.add_argument("--retained", type=Path)
    result.add_argument(
        "--retrieved-at", action="append", default=[], metavar="FILENAME=AWARE_TIME"
    )
    result.add_argument(
        "--output", type=Path, help="New D: receipt file; existing files are never overwritten"
    )
    return result


def main() -> None:
    arguments = parser()
    args = arguments.parse_args()
    try:
        output = local_path(args.output) if args.output else None
        if output and (output.exists() or not output.parent.is_dir()):
            raise ValueError("Output must be a new file in an existing D: directory")
        if args.apply and args.stage != "verify":
            url = urlsplit(args.base_url)
            if (
                url.scheme != "http"
                or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path.rstrip("/") != "/v1/ontology"
            ):
                raise ValueError(
                    "Apply requires a loopback HTTP /v1/ontology endpoint without credentials"
                )
            token = os.environ.get("G8_ONTOLOGY_TOKEN")
            if not token:
                raise ValueError("Set G8_ONTOLOGY_TOKEN to the intended existing maker credential")
            with httpx.Client(
                base_url=args.base_url.rstrip("/") + "/",
                trust_env=False,
                headers={"Authorization": "Bearer " + token},
                timeout=60,
                follow_redirects=False,
            ) as client:
                result = run(args, client)
        else:
            result = run(args)
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if output:
            with output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
    except (ValueError, KeyError, OSError, httpx.HTTPError) as exc:
        # HTTP transport errors can contain URL data; never expose credentials or full responses.
        message = "Local G8 transport failed" if isinstance(exc, httpx.HTTPError) else str(exc)
        arguments.exit(1, message + "\n")


if __name__ == "__main__":
    main()
