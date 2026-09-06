"""Original Matsne captures and reviewed act identity, without legal activation."""

import re
from datetime import UTC, datetime
from difflib import unified_diff
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from uuid import UUID, uuid5

import httpx
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import resources, source_documents
from finai_api.services.workspace import WorkspaceError


class Capture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_number: str = Field(pattern=r"^[1-9][0-9]{0,11}$")
    publication: int = Field(default=0, ge=0, le=10000)


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")
    rationale: str = Field(min_length=10, max_length=2000)


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_version: UUID
    after_version: UUID


def compare(principal, request: Comparison):
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT version_id,attributes FROM resource_versions WHERE tenant_id=%s "
            "AND version_id=ANY(%s::uuid[]) AND object_type='SourceRegulatoryPublication'",
            (principal.scope.tenant_id, [request.before_version, request.after_version]),
        ).fetchall()
    indexed = {row["version_id"]: row for row in rows}
    if request.before_version not in indexed or request.after_version not in indexed:
        raise WorkspaceError(404, "Publication versions unavailable in this context")
    before, after = indexed[request.before_version], indexed[request.after_version]
    if before["attributes"]["act_id"] != after["attributes"]["act_id"]:
        raise WorkspaceError(422, "Compare publications of the same canonical act")
    left, right = before["attributes"]["observation"], after["attributes"]["observation"]
    _, left_document = inspect(principal, before["attributes"]["document_id"])
    _, right_document = inspect(principal, after["attributes"]["document_id"])
    if (
        left_document["text_sha256"] != left["text_sha256"]
        or right_document["text_sha256"] != right["text_sha256"]
    ):
        raise WorkspaceError(409, "Retained text no longer matches the publication parser contract")
    lines = list(
        unified_diff(
            left_document["text"].splitlines(),
            right_document["text"].splitlines(),
            fromfile=str(request.before_version),
            tofile=str(request.after_version),
            lineterm="",
        )
    )
    return {
        "contract": "regulatory-document-diff/1",
        "act_id": before["attributes"]["act_id"],
        "before": {
            "version_id": request.before_version,
            "document_id": before["attributes"]["document_id"],
            "metadata": left["metadata"],
            "completeness": left["completeness"],
        },
        "after": {
            "version_id": request.after_version,
            "document_id": after["attributes"]["document_id"],
            "metadata": right["metadata"],
            "completeness": right["completeness"],
        },
        "state": "DOCUMENT_TEXT_CHANGED"
        if left["text_sha256"] != right["text_sha256"]
        else "DOCUMENT_TEXT_UNCHANGED",
        "diff": lines[:4000],
        "diff_truncated": len(lines) > 4000,
        "legal_change_verified": False,
        "accounting_effects_created": False,
    }


class DocumentText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []
        self.found = 0

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if dict(attrs).get("id") == "maindoc":
                self.depth = 1
                self.found += 1
            elif self.depth:
                self.depth += 1

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and data.strip():
            self.parts.append(" ".join(data.split()))


def parse(content):
    if len(content) > 8_000_000:
        raise WorkspaceError(413, "Regulatory page exceeds 8 MB")
    try:
        html = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise WorkspaceError(422, "Matsne capture must be UTF-8") from exc
    identity = re.search(r"page-document-view-(\d+)\b", html)
    parser = DocumentText()
    parser.feed(html)
    if not identity or parser.found != 1 or not parser.parts:
        raise WorkspaceError(422, "Recognized Matsne act document required")

    def plain(value):
        return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())

    metadata = {}
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) == 2:
            key, value = map(plain, cells)
            if key in {
                "დოკუმენტის ნომერი",
                "დოკუმენტის მიმღები",
                "მიღების თარიღი",
                "გამოქვეყნების წყარო, თარიღი",
                "სარეგისტრაციო კოდი",
            }:
                metadata[key] = value
    if not metadata.get("დოკუმენტის ნომერი"):
        raise WorkspaceError(422, "Act registration metadata unavailable")
    publication = re.search(r"publication_id=(\d+)", html)
    options = sorted(set(int(v) for v in re.findall(r"[?&]publication=(\d+)", html)))
    served = int(publication[1]) if publication else None
    completeness = "UNVERIFIED_COMPLETENESS"
    if served is not None and options and max(options) > served:
        completeness = "OLDER_PUBLICATION_ONLY"
    if "კონსოლიდირებული ვარიანტის ნახვა ფასიანია" in plain(html):
        completeness = "RESTRICTED_CONSOLIDATION"
    title = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.S | re.I)
    text = "\n".join(parser.parts)
    return {
        "parser_version": "matsne-act/1",
        "matsne_id": identity[1],
        "title": plain(title[1]) if title else parser.parts[0],
        "publication": served,
        "advertised_publications": options,
        "metadata": metadata,
        "text_sha256": sha256(text.encode()).hexdigest(),
        "text": text,
        "completeness": completeness,
        "attachments_retained": False,
        "current_law_verified": False,
    }


def capture(principal, request: Capture):
    require_permission(principal, "ingest")
    url = f"https://matsne.gov.ge/ka/document/view/{request.document_number}?publication={request.publication}"
    try:
        with httpx.stream("GET", url, timeout=45, follow_redirects=False) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 8_000_000:
                    raise WorkspaceError(413, "Regulatory page exceeds 8 MB")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise WorkspaceError(
            502, "Official source fetch failed; no legal version was published"
        ) from exc
    content = b"".join(chunks)
    observed = parse(content)
    if (
        observed["matsne_id"] != request.document_number
        or observed["publication"] != request.publication
    ):
        raise WorkspaceError(409, "Official response does not identify the requested publication")
    retained = source_documents.retain_document(
        principal,
        f"matsne-{request.document_number}-publication-{request.publication}.html",
        content,
    )
    return {"document": retained, "observation": observed, "source_url": url}


def inspect(principal, document_id):
    metadata, content = source_documents.document_bytes(principal, document_id)
    return metadata, parse(content)


def propose(principal, request: Publication):
    metadata, observed = inspect(principal, request.document_id)
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    observation = uuid5(evidence, "matsne-publication")
    act = canonical_id(
        principal.scope.tenant_id, "RegulatoryAct", "GE:MATSNE:" + observed["matsne_id"]
    )
    attrs = {
        "document_id": request.document_id,
        "evidence_id": str(evidence),
        "act_id": str(act),
        "observation": {key: value for key, value in observed.items() if key != "text"},
    }
    specs = [
        (
            evidence,
            "SourceEvidence",
            metadata["source_sha256"],
            "Original Matsne capture",
            {"sha256": metadata["source_sha256"], "source_system": "RETAINED_DOCUMENT"},
        ),
        (
            act,
            "RegulatoryAct",
            "GE:MATSNE:" + observed["matsne_id"],
            observed["title"][:200],
            {
                "reference": "MATSNE:" + observed["matsne_id"],
                "jurisdiction": "GE",
                "evidence_id": str(evidence),
            },
        ),
        (
            observation,
            "SourceRegulatoryPublication",
            str(observation),
            observed["title"][:200],
            attrs,
        ),
    ]
    mutations = []
    for identity, kind, key, name, values in specs:
        try:
            current = resources.get_resource(principal, identity)["resource"]
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            current = None
        if current and current["attributes"] == values:
            continue
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                expected_version_id=current["version_id"] if current else None,
                object_type=kind,
                identity_key=key,
                display_name=name,
                attributes=values,
                valid_from=datetime.now(UTC),
                evidence_class="SOURCE_BOUND",
            )
        )
    if not mutations:
        raise WorkspaceError(409, "This source publication is already retained in the ontology")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Bind original regulatory publication",
            rationale=request.rationale,
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        ),
    )


def validate(principal, item, target):
    metadata, observed = inspect(principal, item.attributes["document_id"])
    evidence = target(item.attributes["evidence_id"], str(item.resource_id), "REGULATORY_SOURCE")
    act = target(item.attributes["act_id"], str(item.resource_id), "REGULATORY_ACT_IDENTITY")
    if (
        item.evidence_class != "SOURCE_BOUND"
        or item.attributes["observation"]
        != {key: value for key, value in observed.items() if key != "text"}
        or item.resource_id != uuid5(UUID(item.attributes["evidence_id"]), "matsne-publication")
        or evidence["attributes"]["sha256"] != metadata["source_sha256"]
        or act["attributes"]["reference"] != "MATSNE:" + observed["matsne_id"]
    ):
        raise WorkspaceError(422, "Regulatory observation must match retained original source")
