import json
import secrets
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal

bearer = HTTPBearer(auto_error=False)


def authenticated_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    """Server-owned identity, scope and permissions; secrets never become audit attributes."""
    tokens = json.loads(get_settings().access_tokens.get_secret_value())
    if not tokens:
        raise HTTPException(503, "Access credentials are not configured")
    if credentials:
        for token, grant in tokens.items():
            if secrets.compare_digest(credentials.credentials, token):
                if "scope" in grant:
                    return Principal.model_validate(grant)
                return Principal(
                    actor_id=f"bootstrap-{sha256(token.encode()).hexdigest()[:24]}",
                    display_name="Bootstrap operator",
                    scope=ExactScope.model_validate(grant),
                    permissions=("read", "ingest", "export"),
                )
    raise HTTPException(401, "Invalid bearer credential", headers={"WWW-Authenticate": "Bearer"})


def authorized_scope(
    principal: Annotated[Principal, Depends(authenticated_principal)],
) -> ExactScope:
    require_permission(principal, "read")
    return principal.scope


def require_permission(principal: Principal, permission: str) -> None:
    if permission not in principal.permissions:
        raise HTTPException(403, f"Permission required: {permission}")
