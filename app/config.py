from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.example"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = Field(default=15, alias="JWT_ACCESS_EXPIRE_MINUTES")
    jwt_refresh_expire_days: int = Field(default=7, alias="JWT_REFRESH_EXPIRE_DAYS")
    smtp_host: str = Field(default="mailhog", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="SMTP_PORT")
    smtp_sender: str = Field(default="no-reply@example.com", alias="SMTP_SENDER")
    app_port: int = Field(default=8002, alias="APP_PORT")
    multi_tenant_mode: Literal["row", "schema"] = Field(default="row", alias="MULTI_TENANT_MODE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
