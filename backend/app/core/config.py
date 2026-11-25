from functools import lru_cache
from typing import Literal

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
    refresh_token_days: int = 14  # "remember me" sessions
    session_token_hours: int = 12  # sessions that were not remembered
    cookie_secure: bool = False
    # Where the refresh cookie is sent. If a proxy serves the API under /api, set /api/auth.
    cookie_path: str = "/auth"
    # Which price decides the apparel price slab. Confirm with your accountant (plan item D6).
    gst_slab_basis: Literal["after_discount", "before_discount"] = "after_discount"
    # Discounts above this share of a line need the sale:discount permission.
    free_discount_percent: int = 10
    # Offline POS rules (plan item D2). Devices read these from the catalogue snapshot.
    offline_warn_hours: int = 24  # warn when the device's catalogue is older than this
    offline_block_hours: int = 72  # stop offline selling when it is older than this
    offline_max_sale_age_days: int = 7  # older offline sales need a manager to review them
    sync_batch_max: int = 50
    media_dir: str = "media"
    max_image_bytes: int = 5 * 1024 * 1024
    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _require_real_secret(self) -> "Settings":
        if self.environment != "development" and self.jwt_secret.startswith("dev-only"):
            raise ValueError("JWT_SECRET must be set to a strong random value outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
