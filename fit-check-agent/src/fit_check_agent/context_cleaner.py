from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from fit_check_agent.config import Settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextCleanupResult:
    product_context: dict[str, Any] | str
    cleaned_by_llm: bool
    error: str | None = None


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _clean_metadata(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    useful_prefixes = ("og:", "twitter:", "product:")
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key).lower().startswith(useful_prefixes)
    }


def deterministic_product_context(product_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Small non-LLM fallback that keeps likely product fields and drops page chrome.

    Image URLs are intentionally excluded: the agent downloads product images in
    a separate non-LLM step, so the cleaner only deals with text.
    """
    return {
        "source_url": product_payload.get("url"),
        "title": product_payload.get("title"),
        "metadata": _clean_metadata(product_payload.get("metadata")),
        "structured_product": product_payload.get("structured_product") or [],
        "product_text_blocks": _as_string_list(product_payload.get("product_text_blocks")),
        "selected_text": product_payload.get("selected_text"),
        "size_texts": _as_string_list(product_payload.get("size_texts")),
        "size_chart": product_payload.get("size_chart"),
        "tooltip_texts": _as_string_list(product_payload.get("tooltip_texts")),
        "variant_texts": _as_string_list(product_payload.get("variant_texts")),
    }


def _llm_input(product_payload: Mapping[str, Any]) -> str:
    fallback_context = deterministic_product_context(product_payload)
    fallback_context["raw_description_text"] = str(
        product_payload.get("description_text") or ""
    )
    return json.dumps(fallback_context, ensure_ascii=False, indent=2, default=str)


async def _chat_text(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    system: str,
    user: str,
) -> str:
    url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/local/agent-playground",
        "X-Title": "fit-check-agent",
    }
    body = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
    }

    last_error: Exception | None = None
    for attempt in range(1, settings.cleaner_max_attempts + 1):
        try:
            response = await client.post(url, json=body, headers=headers)
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get("retry-after")
                wait_seconds = float(retry_after) if retry_after else min(
                    30.0,
                    (2 ** (attempt - 1)) + random.random(),
                )
                if attempt < settings.cleaner_max_attempts:
                    logger.info(
                        "product_context_cleaner_retry status=%s wait=%.1fs",
                        response.status_code,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
            if response.status_code >= 400:
                raise RuntimeError(f"http_{response.status_code}: {response.text}")

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("empty cleaner response")
            return content.strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < settings.cleaner_max_attempts:
                wait_seconds = min(30.0, (2 ** (attempt - 1)) + random.random())
                logger.info(
                    "product_context_cleaner_retry attempt=%d/%d wait=%.1fs error=%s",
                    attempt,
                    settings.cleaner_max_attempts,
                    wait_seconds,
                    exc,
                )
                await asyncio.sleep(wait_seconds)
                continue

    raise RuntimeError(str(last_error) if last_error else "cleaner failed")


async def clean_product_context(
    product_payload: Mapping[str, Any],
    *,
    settings: Settings,
) -> ContextCleanupResult:
    if not settings.clean_product_context or not settings.openrouter_api_key:
        return ContextCleanupResult(
            product_context=deterministic_product_context(product_payload),
            cleaned_by_llm=False,
            error=None if settings.openrouter_api_key else "OPENROUTER_API_KEY missing",
        )

    system = """You clean noisy ecommerce browser extraction for a fashion try-on.

Keep only product facts that help judge whether a garment will look good on a person: brand, product name, category, gender, color, fabric/material, fit, pattern, sleeve, neckline, length, price, availability, size options, selected size, size chart/measurements, size-chart image URL, size-fit notes, and tooltip/help text about sizing or variants.

Return concise Markdown with these headings only:
- Product
- Visual Details
- Size And Fit
- Tooltips Or Hidden Size Text
- Missing Or Unclear

Remove global navigation, footer links, login/account text, ads, unrelated category menus, coupons, SEO boilerplate, and duplicate text. Preserve every size-chart row and measurement from structured size_chart data; do not summarize away rows, units, labels, or measurement names. Preserve uncertain but relevant size/fit text. Do not invent facts."""

    user = _llm_input(product_payload)
    try:
        timeout = httpx.Timeout(settings.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            cleaned = await _chat_text(
                client=client,
                settings=settings,
                system=system,
                user=user,
            )
        return ContextCleanupResult(product_context=cleaned, cleaned_by_llm=True)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.info("product_context_cleaner_fallback error=%s", exc)
        return ContextCleanupResult(
            product_context=deterministic_product_context(product_payload),
            cleaned_by_llm=False,
            error=str(exc),
        )
