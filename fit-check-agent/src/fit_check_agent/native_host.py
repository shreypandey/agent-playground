from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
from typing import Any, BinaryIO

from fit_check_agent.config import Settings
from fit_check_agent.pipeline import run_fit_check
from fit_check_agent.profiles import ProfileError, discover_profiles


HOST_NAME = "com.agent_playground.fit_check"
MAX_NATIVE_MESSAGE_BYTES = 8 * 1024 * 1024


logger = logging.getLogger(__name__)


class NativeMessageError(ValueError):
    """Raised for malformed Native Messaging messages."""


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise NativeMessageError("unexpected EOF while reading message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_native_message(stream: BinaryIO) -> dict[str, Any] | None:
    length_bytes = stream.read(4)
    if not length_bytes:
        return None
    if len(length_bytes) != 4:
        raise NativeMessageError("incomplete message length")

    length = struct.unpack("<I", length_bytes)[0]
    if length > MAX_NATIVE_MESSAGE_BYTES:
        raise NativeMessageError(f"message too large: {length}")

    payload = _read_exact(stream, length)
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise NativeMessageError("message must be a JSON object")
    return message


def write_native_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


async def handle_message(message: dict[str, Any]) -> dict[str, Any]:
    action = message.get("action")
    settings = Settings()

    if action == "list_profiles":
        return {
            "ok": True,
            "host": HOST_NAME,
            "profiles": discover_profiles(settings.profiles_dir),
        }

    if action == "fit_check":
        profile_name = message.get("profile_name")
        product_payload = message.get("product")
        if not isinstance(product_payload, dict):
            return {"ok": False, "error": "product must be a JSON object"}

        result = await run_fit_check(
            profile_name=str(profile_name or ""),
            product_payload=product_payload,
            settings=settings,
        )
        return {
            "ok": True,
            "message": "Sent fit-check prompt to ChatGPT.",
            "profile_name": result.profile_name,
            "profile_images": result.profile_images,
            "product_image_url_candidates": result.product_image_url_candidates,
            "product_image_urls": result.product_image_urls,
            "product_images_fetched": result.product_images_fetched,
            "uploaded_images": result.uploaded_images,
            "context_cleaned": result.context_cleaned,
            "context_cleaner_error": result.context_cleaner_error,
        }

    return {"ok": False, "error": f"unknown action: {action}"}


async def _handle_safely(message: dict[str, Any]) -> dict[str, Any]:
    try:
        return await handle_message(message)
    except ProfileError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # Native Messaging stdout must remain protocol-only.
        logger.exception("native_host_error")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        message = read_native_message(sys.stdin.buffer)
        if message is None:
            return 0
        response = asyncio.run(_handle_safely(message))
        write_native_message(sys.stdout.buffer, response)
    except Exception as exc:
        logger.exception("native_host_protocol_error")
        try:
            write_native_message(
                sys.stdout.buffer,
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            )
        except Exception:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
