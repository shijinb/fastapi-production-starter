"""Application settings, loaded from environment variables (and a local .env file in development)."""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FastAPI Production Starter"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/app"
    database_pool_size: int = Field(default=5, ge=1)
    database_echo: bool = False

    jwt_secret: SecretStr = SecretStr(INSECURE_DEV_SECRET)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=24 * 60)
    refresh_token_ttl_days: int = Field(default=14, ge=1, le=90)

    # NoDecode: read the raw env value so split_origins can accept a comma-separated list, not only JSON.
    cors_origins: Annotated[list[str], NoDecode] = []
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # Expose /docs and /openapi.json. Disable in production if the API is not meant to be public.
    docs_enabled: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        # Allows CORS_ORIGINS=http://localhost:3000,https://admin.example.com
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def require_real_secret_in_production(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if self.app_env == "production" and (secret == INSECURE_DEV_SECRET or len(secret) < 32):
            raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
