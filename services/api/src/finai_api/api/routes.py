from fastapi import APIRouter

from finai_api.config import get_settings
from finai_api.domain.authority import CompileHydrationRequest, ConstructionReceipt
from finai_api.services.authority_compiler import AuthorityCompiler

router = APIRouter()
compiler = AuthorityCompiler()


@router.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": settings.api_version,
        "environment": settings.environment,
    }


@router.post(
    "/v1/hydration/compile",
    response_model=ConstructionReceipt,
    tags=["enterprise hydration"],
)
def compile_hydration(request: CompileHydrationRequest) -> ConstructionReceipt:
    return compiler.compile(request)
