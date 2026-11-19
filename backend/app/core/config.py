from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Wearstack"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://wearstack:wearstack@localhost:5434/wearstack"
    jwt_secret: str = "dev-only-change-me-not-for-production-use"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _require_real_secret(self) -> "Settings":
        if self.environment != "development" and self.jwt_secret.startswith("dev-only"):
            raise ValueError("JWT_SECRET must be set to a strong random value outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
