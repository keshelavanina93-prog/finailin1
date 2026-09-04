from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINAI_", extra="ignore")

    environment: str = "local"
    service_name: str = "finai-api"
    api_version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
