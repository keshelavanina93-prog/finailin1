import json
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope

bearer = HTTPBearer(auto_error=False)


def authorized_scope(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> ExactScope:
    """Bootstrap credentials grant one exact scope. Never trust client tenant headers."""
    tokens = json.loads(get_settings().access_tokens.get_secret_value())
    if not tokens:
        raise HTTPException(503, "Access credentials are not configured")
    if credentials:
        for token, scope in tokens.items():
            if secrets.compare_digest(credentials.credentials, token):
                return ExactScope.model_validate(scope)
    raise HTTPException(401, "Invalid bearer credential", headers={"WWW-Authenticate": "Bearer"})
