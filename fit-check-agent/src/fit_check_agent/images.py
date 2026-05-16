from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx


def is_transformed_url(url: str) -> bool:
    """True if the URL path encodes Cloudinary/Myntra-style transforms.

    These CDNs embed sizing/format params as comma-separated key_value path
    segments (e.g. ``/h_1440,q_100,w_1080/`` or ``/f_webp,h_560,q_90,w_420/``).
    A comma in the path is a reliable signal that the URL is a derivative,
    not the original asset.
    """
    if not isinstance(url, str):
        return False
    return "," in urlparse(url).path


def select_original_image_urls(urls: list[str]) -> list[str]:
    """Keep only URLs without transform/sizing params in the path.

    Product pages on Myntra/Cloudinary-backed CDNs surface dozens of derivative
    image URLs (thumbnails, related-product carousels, retina variants). The
    untransformed originals are the canonical product photos we want to feed to
    the model.
    """
    return [url for url in urls if not is_transformed_url(url)]


logger = logging.getLogger(__name__)


DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_IMAGES = 8
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heic",
    "image/avif": ".avif",
}

_KNOWN_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".avif"}


def _safe_extension(url: str, content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime]
    if mime:
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _KNOWN_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


async def _fetch_one(
    *,
    client: httpx.AsyncClient,
    url: str,
    index: int,
    target_dir: Path,
    max_bytes: int,
) -> Path | None:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        logger.info("product_image_fetch_error url=%s error=%s", url, exc)
        return None

    if response.status_code >= 400:
        logger.info(
            "product_image_fetch_status url=%s status=%s",
            url,
            response.status_code,
        )
        return None

    content_type = response.headers.get("content-type", "")
    if not content_type.lower().startswith("image/"):
        logger.info(
            "product_image_fetch_skip_mime url=%s content_type=%s",
            url,
            content_type,
        )
        return None

    data = response.content
    if not data:
        return None
    if len(data) > max_bytes:
        logger.info(
            "product_image_fetch_too_large url=%s bytes=%d limit=%d",
            url,
            len(data),
            max_bytes,
        )
        return None

    suffix = _safe_extension(url, content_type)
    out_path = target_dir / f"product_{index:02d}{suffix}"
    out_path.write_bytes(data)
    return out_path


async def fetch_product_images(
    urls: list[str],
    *,
    target_dir: Path,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    request_timeout_seconds: float = 20.0,
) -> list[Path]:
    """Download product image URLs into target_dir. LLM-free."""
    if not urls:
        return []

    target_dir.mkdir(parents=True, exist_ok=True)
    selected = urls[:max_images]
    timeout = httpx.Timeout(request_timeout_seconds)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "image/*,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(
                _fetch_one(
                    client=client,
                    url=url,
                    index=i,
                    target_dir=target_dir,
                    max_bytes=max_bytes,
                )
                for i, url in enumerate(selected, start=1)
            )
        )
    return [path for path in results if path is not None]
