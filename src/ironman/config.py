from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IRONMAN_", env_file=".env", extra="ignore")

    # Roles: the private API and workers use database_url; the public API must use
    # public_database_url, whose role can only read the `public` schema.
    database_url: str = "postgresql://ironman:ironman@localhost:5432/ironman"
    public_database_url: str = "postgresql://ironman_public:ironman_public@localhost:5432/ironman"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = "dev-only-change-me"  # signs sessions and share links
    token_enc_key: str = ""  # Fernet key for stored OAuth tokens
    pseudonym_key: str = "dev-only-pseudonym-key"  # HMAC key for public IDs

    owner_email: str = "owner@example.com"
    session_ttl_s: int = 8 * 3600

    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_verify_token: str = "ironman-verify"
    strava_redirect_uri: str = "http://localhost:8000/api/strava/callback"

    llm_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"
    llm_max_calls_per_day: int = 10
    inference_url: str = "http://localhost:8002"

    public_rate_limit_per_min: int = 60
    max_weekly_load_increase: float = 0.10
    public_hide_hr: bool = False
    web_origin: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
