from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://enrich:enrich@localhost:5432/enrich"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    llm_timeout_seconds: float = 15.0

    source_reliability: dict[str, float] = {
        "company_registry": 0.95,
        "professional_profiles": 0.85,
        "email_pattern": 0.7,
        "web_mentions": 0.5,
    }
    email_patterns: dict[str, str] = {"acme.com": "first.last", "northwind.io": "first"}

    cache_ttl_seconds: int = 6 * 3600
    verify_below_confidence: float = 0.75
    max_job_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
