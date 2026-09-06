"""Resolve current effective identity separately from its latest editing head."""

from datetime import datetime
from typing import Any
from uuid import UUID


def retained_with_effective_version(
    cursor: Any, tenant: UUID, resource: UUID, version: UUID, at: datetime
) -> Any:
    # The same RLS-invoker function protects lifecycle and consumption SQL writes.
    # Select the temporal winner before checking its state: revocation cannot
    # expose an earlier approved version as current truth.
    return cursor.execute(
        "SELECT v.*,g8_effective_version_id(v.tenant_id,v.resource_id,%s) "
        "AS effective_version_id FROM resource_versions v WHERE v.tenant_id=%s "
        "AND v.resource_id=%s AND v.version_id=%s",
        (at, tenant, resource, version),
    ).fetchone()
