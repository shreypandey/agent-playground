from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from shared.chatgpt_web import send_to_chatgpt

from fit_check_agent.config import Settings
from fit_check_agent.context_cleaner import clean_product_context
from fit_check_agent.images import fetch_product_images, select_original_image_urls
from fit_check_agent.profiles import load_profile_bundle
from fit_check_agent.prompt import build_fit_check_prompt


@dataclass(frozen=True)
class FitCheckResult:
    profile_name: str
    profile_images: int
    product_image_url_candidates: int
    product_image_urls: int
    product_images_fetched: int
    uploaded_images: int
    context_cleaned: bool
    context_cleaner_error: str | None = None


def _product_image_urls(candidates: object) -> list[str]:
    if not isinstance(candidates, list):
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        url = candidate.strip()
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        seen.add(url)
        urls.append(url)
    return urls


async def run_fit_check(
    *,
    profile_name: str,
    product_payload: Mapping[str, Any],
    settings: Settings | None = None,
) -> FitCheckResult:
    settings = settings or Settings()
    profile_bundle = load_profile_bundle(
        settings.profiles_dir,
        profile_name,
    )

    candidate_urls = _product_image_urls(
        product_payload.get("structured_image_urls"),
    )
    product_image_urls = select_original_image_urls(candidate_urls)
    cleanup = await clean_product_context(product_payload, settings=settings)

    with tempfile.TemporaryDirectory(prefix="fitcheck-product-") as tmp_dir:
        fetched_paths = await fetch_product_images(
            product_image_urls,
            target_dir=Path(tmp_dir),
            max_images=settings.product_image_max_count,
            max_bytes=settings.product_image_max_bytes,
            request_timeout_seconds=settings.request_timeout_seconds,
        )

        prompt = build_fit_check_prompt(
            profile_bundle=profile_bundle,
            product_payload=cleanup.product_context,
            profile_image_count=len(profile_bundle.image_paths),
            product_image_count=len(fetched_paths),
        )
        image_paths = [*profile_bundle.image_paths, *fetched_paths]

        send_to_chatgpt(
            prompt,
            image_paths,
            url=settings.chatgpt_url,
            wait_seconds=settings.chatgpt_wait_seconds,
            image_settle_seconds=settings.chatgpt_image_settle_seconds,
            final_settle_seconds=settings.chatgpt_final_settle_seconds,
            submit_attempts=settings.chatgpt_submit_attempts,
            submit_retry_seconds=settings.chatgpt_submit_retry_seconds,
        )

    return FitCheckResult(
        profile_name=profile_bundle.name,
        profile_images=len(profile_bundle.image_paths),
        product_image_url_candidates=len(candidate_urls),
        product_image_urls=len(product_image_urls),
        product_images_fetched=len(fetched_paths),
        uploaded_images=len(image_paths),
        context_cleaned=cleanup.cleaned_by_llm,
        context_cleaner_error=cleanup.error,
    )
