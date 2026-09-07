"""Atomic journal bundle validation inside the shared canonical transaction."""

from psycopg.rows import dict_row

from finai_api.domain.journal_balance import JournalManifest, balanced_amounts
from finai_api.services.workspace import WorkspaceError


def validate_bundle(conn, principal, proposal) -> list[dict]:
    mutations = {str(item.resource_id): item for item in proposal.mutations}
    journals = {key: item for key, item in mutations.items() if item.object_type == "JournalEntry"}
    lines = {key: item for key, item in mutations.items() if item.object_type == "JournalLine"}
    if not journals and not lines:
        return []
    for line in lines.values():
        if line.attributes.get("journal_id") not in journals:
            raise WorkspaceError(
                422, "Journal lines require their complete entry in the same proposal"
            )
    touched = list(journals | lines)
    with conn.cursor(row_factory=dict_row) as cursor:
        # Editing heads include future-effective versions: omitting one cannot silently remove it.
        retained = cursor.execute(
            "SELECT v.* FROM resource_heads h JOIN resource_versions v "
            "ON v.tenant_id=h.tenant_id AND v.version_id=h.version_id "
            "WHERE h.tenant_id=%s AND (h.resource_id=ANY(%s::uuid[]) OR "
            "(v.object_type='JournalLine' AND v.attributes->>'journal_id'=ANY(%s::text[])))",
            (principal.scope.tenant_id, touched, list(journals)),
        ).fetchall()
    for old in retained:
        key = str(old["resource_id"])
        current = mutations.get(key)
        if current is None or str(current.expected_version_id) != str(old["version_id"]):
            raise WorkspaceError(
                409, "Journal publication requires every retained line editing head"
            )
        if old["object_type"] == "JournalLine" and (
            current.attributes.get("journal_id") != old["attributes"].get("journal_id")
        ):
            raise WorkspaceError(422, "Journal lines cannot be reparented")
    summaries = []
    for key, entry in journals.items():
        try:
            manifest = JournalManifest.model_validate(entry.attributes.get("definition"))
            members = {str(value) for value in manifest.line_ids}
            attached = {
                identity
                for identity, line in lines.items()
                if line.attributes.get("journal_id") == key
            }
            if members != attached:
                raise ValueError("Journal requires exactly its complete declared line set")
            bundle = [lines[identity] for identity in sorted(members)]
            for item in [entry, *bundle]:
                if item.authority_state != "APPROVED":
                    raise ValueError("Journal revocation requires a separate governed contract")
                if (item.valid_from, item.valid_to) != (entry.valid_from, entry.valid_to):
                    raise ValueError("Journal entry and lines require one effective interval")
                if item.attributes.get("accounting_binding_id") != entry.attributes.get(
                    "accounting_binding_id"
                ):
                    raise ValueError(
                        "Journal entry and lines require one accepted accounting binding"
                    )
            currencies = {line.attributes["amount"]["currency_id"] for line in bundle}
            if len(currencies) != 1:
                raise ValueError("Journal requires one canonical currency")
            totals = balanced_amounts([line.attributes for line in bundle])
            summaries.append(
                {
                    "journal_id": key,
                    "contract": manifest.contract,
                    "line_count": len(bundle),
                    "currency_id": next(iter(currencies)),
                    **totals,
                    "status": "BALANCED",
                }
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise WorkspaceError(422, str(exc)) from exc
    return summaries
