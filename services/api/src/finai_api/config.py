from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINAI_", extra="ignore")

    environment: str = "local"
    service_name: str = "finai-api"
    api_version: str = "0.1.0"
    database_url: SecretStr = SecretStr("")
    s3_endpoint: str = ""
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "g8-evidence"
    s3_region: str = "us-east-1"
    access_tokens: SecretStr = SecretStr("{}")
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"


@lru_cache
def get_settings() -> Settings:
    return Settings()
