from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"
RUNS_DIR = ROOT / "runs"


class Settings(BaseSettings):
    """Read from environment variables or `.env` (names are case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: SecretStr
    rasid_model: str = "claude-sonnet-5-5"
    rasid_password: SecretStr | None = None
    # Output ceiling per call. Long articles need room for the full Arabic translation + fact table.
    rasid_max_tokens: int = 32000
    # Server-side refusal fallback ("default" routing). Not available for Haiku models.
    rasid_fallbacks: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
