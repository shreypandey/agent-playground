from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    """Permanent failure — do NOT retry (bad schema, null content, malformed JSON)."""


class RetryableOpenRouterError(OpenRouterError):
    """Transient failure — safe to retry (429, 5xx, transport)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _wait_strategy(retry_state: RetryCallState) -> float:
    """Honor Retry-After if the server provided one; else exponential + jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, RetryableOpenRouterError) and exc.retry_after is not None:
        return float(exc.retry_after)
    return wait_random_exponential(multiplier=1, max=30)(retry_state)


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.info(
        "openrouter_retry attempt=%d/%d next_wait=%.1fs error=%s",
        retry_state.attempt_number,
        retry_state.retry_object.stop.max_attempt_number,  # type: ignore[attr-defined]
        retry_state.next_action.sleep if retry_state.next_action else 0.0,
        exc,
    )


async def _post_once(
    client: httpx.AsyncClient,
    *,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    """One HTTP attempt. Raises RetryableOpenRouterError on transient failures,
    OpenRouterError on permanent failures, returns parsed JSON dict on success.
    """
    try:
        resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise RetryableOpenRouterError(f"transport_error: {exc}") from exc

    if resp.status_code in (429, 500, 502, 503, 504):
        retry_after = resp.headers.get("retry-after")
        ra = float(retry_after) if retry_after else None
        raise RetryableOpenRouterError(f"status_{resp.status_code}", retry_after=ra)

    if resp.status_code >= 400:
        raise OpenRouterError(f"http_{resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, ValueError, IndexError) as exc:
        raise OpenRouterError(f"bad_response_shape: {exc}") from exc

    if content is None:
        raise OpenRouterError(
            f"null_content (model refused or filtered) finish_reason="
            f"{data['choices'][0].get('finish_reason')!r}"
        )

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OpenRouterError(
            f"json_decode_failed: {exc}; raw={content[:200]}"
        ) from exc


async def chat_json(
    client: httpx.AsyncClient,
    *,
    model: str,
    system: str,
    user: str,
    response_schema: dict[str, Any],
    api_key: str,
    base_url: str = "https://openrouter.ai/api/v1",
    temperature: float = 0.0,
    referer: str = "https://github.com/local/agents-workspace",
    title: str = "agents-workspace",
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Chat completion via OpenRouter with json_schema-structured output.

    Retries automatically on 429/5xx/transport errors via tenacity, honoring
    Retry-After when present, otherwise exponential backoff with jitter (capped
    at 30s). Permanent errors (malformed response, null content, JSON decode)
    raise immediately without retry.
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_schema", "json_schema": response_schema},
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": title,
    }
    url = base_url.rstrip("/") + "/chat/completions"

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(RetryableOpenRouterError),
        stop=stop_after_attempt(max_attempts),
        wait=_wait_strategy,
        before_sleep=_log_retry,
        reraise=True,
    ):
        with attempt:
            return await _post_once(client, url=url, body=body, headers=headers)

    raise OpenRouterError("unreachable")  # pragma: no cover
