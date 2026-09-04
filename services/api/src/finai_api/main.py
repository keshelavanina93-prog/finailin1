from fastapi import FastAPI

from finai_api.api.routes import router

app = FastAPI(
    title="FinAI / NYX Core API",
    summary="Evidence-native enterprise operating platform",
    version="0.1.0",
)
app.include_router(router)
