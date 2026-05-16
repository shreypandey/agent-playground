from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # Env precedence (last wins on conflict): root .env  <  agent .env  <  shell env.
    # `../.env` resolves relative to the CWD at invocation. run.sh cds into the
    # agent dir before launching, so the paths below are correct in normal use.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Shared (typically come from ../.env, but agent .env or shell can override)
    openrouter_api_key: str
    openrouter_model: str = "anthropic/claude-haiku-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Telegram destinations. Accepts comma-separated values via either env name.
    telegram_bot_token: str
    telegram_chat_ids: Annotated[list[str], NoDecode] = Field(
        validation_alias=AliasChoices("TELEGRAM_CHAT_IDS", "TELEGRAM_CHAT_ID"),
    )

    @field_validator("telegram_chat_ids", mode="before")
    @classmethod
    def _split_chat_ids(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        raise TypeError("telegram_chat_ids must be a string or list")

    # Filter knobs
    min_salary_inr_lpa: float = 50.0
    usd_to_inr_fallback: float = 83.0
    max_notifications_per_run: int = 10

    # Runtime knobs
    hn_hiring_user: str = "whoishiring"
    state_file: Path = Path("state/seen_ids.json")
    max_comments: int = 400
    request_timeout_seconds: float = 30.0
