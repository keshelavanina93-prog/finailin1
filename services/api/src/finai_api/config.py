from functools import lru_cache

from pydantic import Field, SecretStr
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
    dev_login_enabled: bool = False
    dev_username: str = ""
    dev_password: SecretStr = SecretStr("")
    dev_access_token: SecretStr = SecretStr("")
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = Field(
        default="g8-report-source-v1", pattern=r"^[a-z][a-z0-9-]{0,95}$"
    )
    petroleum_action_adapter: str = "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()
