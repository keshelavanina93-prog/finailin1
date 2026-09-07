"""Exact retained-definition reads shared by tested semantic projection operators."""

import json
import re
from contextlib import contextmanager
from hashlib import sha256
from uuid import UUID

from psycopg.types.json import Jsonb

from finai_api.domain.semantic_analysis import Pin, Value
from finai_api.services.workspace import WorkspaceError


def digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def pin(row):
    return Pin.model_validate(
        {key: row[key] for key in ("resource_id", "version_id", "content_hash")}
    )


def row_key(run_id, original_group_key):
    # A locator inside an immutable result, never a new canonical object identity.
    return "row_" + digest([run_id, original_group_key])


def field_label(name, spec):
    label = spec.get("label") or spec.get("display_name")
    return (
        label if isinstance(label, str) and label.strip() else name.replace("_", " ").capitalize()
    )


def value_options(rows, field):
    result: dict[str, Value] = {}
    for row in rows:
        value = row.values[field]
        result.setdefault(digest(value.model_dump(mode="json")), value)
    return list(result.values())


class Resolver:
    """RLS remains active; no current-head substitution for an older retained result."""

    def __init__(self, principal, plan):
        self.principal = principal
        self.pins = plan["static_dependencies"] + [plan["function"]]
        self.cache = {}
        self.dependency_cache = {}
        self.source_cache = {}
        self.construction_sources = {}
        self._cursor = None

    @contextmanager
    def read_session(self):
        """One authorized read transaction per projection; never shared between requests."""
        from finai_api.services.function_invocations import _database

        if self._cursor is not None:
            raise RuntimeError("Analysis read session is already active")
        with _database(self.principal) as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            self._cursor = cursor
            try:
                yield self
            finally:
                self._cursor = None

    @contextmanager
    def database(self):
        if self._cursor is not None:
            yield self._cursor
        else:
            with self.read_session():
                yield self._cursor

    def version(self, reference):
        if isinstance(reference, Pin):
            reference = reference.model_dump(mode="json")
        rid, vid = UUID(str(reference["resource_id"])), UUID(str(reference["version_id"]))
        key = (rid, vid)
        if key not in self.cache:
            if len(self.cache) >= 2000:
                raise WorkspaceError(422, "Analysis definition read budget exceeded")
            with self.database() as c:
                row = c.execute(
                    "SELECT v.*,i.identity_key FROM resource_versions v "
                    "JOIN canonical_identities i "
                    "USING(tenant_id,resource_id) WHERE v.tenant_id=%s AND v.resource_id=%s "
                    "AND v.version_id=%s",
                    (self.principal.scope.tenant_id, rid, vid),
                ).fetchone()
            if row is None:
                raise WorkspaceError(404, "Analysis input unavailable in current access context")
            self.cache[key] = row
        row = self.cache[key]
        if reference.get("content_hash") and row["content_hash"] != reference["content_hash"]:
            raise WorkspaceError(409, "Analysis input differs from its retained version")
        return row

    def for_id(self, resource_id):
        matches = {
            str(ref["version_id"]): ref
            for ref in self.pins
            if str(ref["resource_id"]) == str(resource_id)
        }
        if len(matches) != 1:
            raise WorkspaceError(409, "Analysis requires one exact retained definition version")
        return self.version(next(iter(matches.values())))

    def dependencies(self, reference):
        row = self.version(reference)
        key = str(row["version_id"])
        if key not in self.dependency_cache:
            with self.database() as c:
                rows = c.execute(
                    "SELECT d.relation,v.*,i.identity_key FROM resource_dependencies d "
                    "JOIN resource_versions v ON v.tenant_id=d.tenant_id "
                    "AND v.version_id=d.target_version_id JOIN canonical_identities i "
                    "ON i.tenant_id=v.tenant_id AND i.resource_id=v.resource_id "
                    "WHERE d.tenant_id=%s AND d.version_id=%s ORDER BY d.relation,v.version_id",
                    (self.principal.scope.tenant_id, row["version_id"]),
                ).fetchall()
            self.dependency_cache[key] = rows
        return self.dependency_cache[key]

    def reference_value(self, resource_id):
        row = self.for_id(resource_id)
        return Value(value=str(row["resource_id"]), label=row["display_name"], reference=pin(row))

    def field(self, row, name):
        matches = [
            item
            for item in self.dependencies(pin(row))
            if item["relation"] == "FIELD:" + name
            and str(item["resource_id"]) == str(row["attributes"].get(name))
        ]
        if len(matches) != 1:
            raise WorkspaceError(409, "Analysis field lacks an exact retained reference")
        return matches[0]

    def source_cells(self, evidence_pin, coordinate):
        """Resolve original evidence by exact hash and scope, never a guessed document ID."""
        from finai_api.services.source_document_preview import preview

        evidence = self.version(evidence_pin)
        if evidence["object_type"] != "SourceEvidence":
            raise WorkspaceError(409, "Original cells require exact source evidence")
        match = re.fullmatch(r"(.+)!(?:([A-Z]{1,3})|row:)?([1-9][0-9]{0,6})", coordinate)
        if match is None:
            return None
        sheet, column, number = match.groups()
        digest_value = evidence["attributes"]["sha256"]
        scope = self.principal.scope.model_dump(mode="json")
        cache_key = (digest_value, sheet, number)
        if cache_key not in self.source_cache:
            if len(self.source_cache) >= 1000:
                raise WorkspaceError(422, "Original cell inspection budget exceeded")
            with self.database() as c:
                matches = c.execute(
                    "SELECT document_id FROM source_documents WHERE tenant_id=%s "
                    "AND exact_scope=%s AND source_sha256=%s LIMIT 2",
                    (self.principal.scope.tenant_id, Jsonb(scope), digest_value),
                ).fetchall()
            if not matches:
                self.source_cache[cache_key] = self._construction_cells(digest_value, sheet, number)
            elif len(matches) != 1:
                raise WorkspaceError(409, "Original evidence document is ambiguous")
            else:
                try:
                    page = preview(
                        self.principal, matches[0]["document_id"], sheet, int(number) - 1, 1
                    )
                except WorkspaceError as exc:
                    if exc.status not in (404, 422):
                        raise
                    page = None
                if page is not None and page["sha256"] != digest_value:
                    raise WorkspaceError(409, "Original cells differ from their source evidence")
                self.source_cache[cache_key] = page
        page = self.source_cache[cache_key]
        if page is None:
            return None
        cells = [
            cell
            for row in page["rows"]
            for cell in row["cells"]
            if column is None or cell["coordinate"] == coordinate
        ]
        if not cells:
            raise WorkspaceError(409, "Original coordinate is outside the retained worksheet")
        return {
            "document_id": page["document_id"],
            "source_sha256": digest_value,
            "sheet": sheet,
            "coordinate": coordinate,
            "cells": [
                {
                    "label": cell["coordinate"] + " · Original worksheet value",
                    "coordinate": cell["coordinate"],
                    "value": str(cell["value"])
                    if isinstance(cell["value"], float)
                    else cell["value"],
                    "formula": cell.get("formula"),
                }
                for cell in cells
            ],
        }

    def _construction_cells(self, source_sha256, sheet, number):
        """Read an existing construction's OOXML bytes through the shared source authority."""
        from finai_api.services.accounting_source_document import read_source
        from finai_api.services.workbook_source import read_workbook

        if source_sha256 not in self.construction_sources:
            if len(self.construction_sources) >= 8:
                raise WorkspaceError(422, "Narrow original evidence to at most eight workbooks")
            with self.database() as c:
                retained = c.execute(
                    "SELECT receipt_id FROM hydration_runs WHERE tenant_id=%s AND exact_scope=%s "
                    "AND source_sha256=%s ORDER BY ingested_at,receipt_id LIMIT 1",
                    (
                        self.principal.scope.tenant_id,
                        Jsonb(self.principal.scope.model_dump(mode="json")),
                        source_sha256,
                    ),
                ).fetchone()
            if retained is None:
                self.construction_sources[source_sha256] = None
            else:
                metadata, content = read_source(self.principal, retained["receipt_id"])
                if (
                    metadata["source_sha256"] != source_sha256
                    or sha256(content).hexdigest() != source_sha256
                ):
                    raise WorkspaceError(409, "Construction bytes differ from original evidence")
                if not content.startswith(b"PK"):
                    self.construction_sources[source_sha256] = None
                else:
                    try:
                        workbook = read_workbook(content)
                    except ValueError as exc:
                        raise WorkspaceError(
                            409, "Original workbook cannot be inspected safely"
                        ) from exc
                    self.construction_sources[source_sha256] = (metadata, workbook)
        retained = self.construction_sources[source_sha256]
        if retained is None:
            return None
        metadata, workbook = retained
        sheets = [item for item in workbook["sheets"] if item["name"] == sheet]
        if len(sheets) != 1:
            raise WorkspaceError(409, "Original worksheet is unavailable or ambiguous")
        cells = [
            {
                "coordinate": sheet + "!" + address,
                "value": cell["value"],
                "formula": cell.get("formula"),
            }
            for address, cell in sheets[0]["cells"].items()
            if re.fullmatch(r"[A-Z]+" + number, address)
        ]
        return {
            "document_id": metadata["document_id"],
            "sha256": source_sha256,
            "rows": [{"row": int(number), "cells": cells}],
        }
