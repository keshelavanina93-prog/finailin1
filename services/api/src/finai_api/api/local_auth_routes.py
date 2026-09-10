from typing import Any

import json
import secrets
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, HTTPException

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal

router = APIRouter(prefix="/v1/auth", tags=["local development authentication"])


class LocalLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LocalLoginResponse(BaseModel):
    access_token: str
    principal: Principal


@router.post("/local-login", response_model=LocalLoginResponse)
def local_login(request: LocalLoginRequest) -> dict[str, Any]:
    settings = get_settings()
    if settings.environment.lower() != "local" or not settings.dev_login_enabled:
        raise HTTPException(404, "Local development login is disabled")
    if not secrets.compare_digest(request.username, settings.dev_username) or not secrets.compare_digest(
        request.password, settings.dev_password.get_secret_value()
    ):
        raise HTTPException(401, "Invalid local development credentials")

    token = settings.dev_access_token.get_secret_value()
    grants = json.loads(settings.access_tokens.get_secret_value())
    grant = grants.get(token)
    if not token or not isinstance(grant, dict):
        raise HTTPException(503, "Local development access token is not configured")
    scope = ExactScope.model_validate(grant.get("scope", grant))
    principal = Principal(
        actor_id="nyxcore-local-operator",
        display_name="NYXCore local operator",
        scope=scope,
        permissions=("read", "ingest", "review", "export", "ontology_read", "ontology_propose"),
    )
    return {"access_token": token, "principal": principal}
