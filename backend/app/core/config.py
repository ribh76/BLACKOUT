import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("ENVIRONMENT", "development")
    ai_provider: str = os.getenv("AI_PROVIDER", "anthropic")
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    nebius_api_key: str | None = os.getenv("NEBIUS_API_KEY") or None
    nebius_base_url: str | None = os.getenv("NEBIUS_BASE_URL") or None
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",")
        if origin.strip()
    )


settings = Settings()
