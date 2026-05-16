from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Env precedence (last wins): root .env < agent .env < shell env.
    # native-host.sh cds into fit-check-agent/ before launching this package.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    profiles_dir: Path = Field(
        default=Path("profiles"),
        validation_alias="FIT_CHECK_PROFILES_DIR",
    )

    chatgpt_url: str = "https://chatgpt.com/"
    chatgpt_wait_seconds: float = 3.0
    chatgpt_image_settle_seconds: float = 3.0
    chatgpt_final_settle_seconds: float = 6.0
    chatgpt_submit_attempts: int = 6
    chatgpt_submit_retry_seconds: float = 2.0

    # Optional LLM cleanup for noisy browser extraction payloads.
    openrouter_api_key: str | None = None
    openrouter_model: str = "anthropic/claude-haiku-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    clean_product_context: Annotated[bool, Field(validation_alias=AliasChoices(
        "FIT_CHECK_CLEAN_PRODUCT_CONTEXT",
        "CLEAN_PRODUCT_CONTEXT",
    ))] = True
    cleaner_max_attempts: int = Field(
        default=5,
        validation_alias="FIT_CHECK_CLEANER_MAX_ATTEMPTS",
    )

    request_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="FIT_CHECK_REQUEST_TIMEOUT_SECONDS",
    )

    product_image_max_count: int = Field(
        default=6,
        validation_alias="FIT_CHECK_PRODUCT_IMAGE_MAX_COUNT",
    )
    product_image_max_bytes: int = Field(
        default=8 * 1024 * 1024,
        validation_alias="FIT_CHECK_PRODUCT_IMAGE_MAX_BYTES",
    )

    @field_validator(
        "chatgpt_wait_seconds",
        "chatgpt_image_settle_seconds",
        "chatgpt_final_settle_seconds",
        "chatgpt_submit_retry_seconds",
        "request_timeout_seconds",
    )
    @classmethod
    def _positive_float(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator(
        "cleaner_max_attempts",
        "chatgpt_submit_attempts",
        "product_image_max_count",
        "product_image_max_bytes",
    )
    @classmethod
    def _positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value
