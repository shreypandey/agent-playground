from __future__ import annotations

import logging
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_MAX = 4096


class TelegramNotifier:
    """Async Telegram sendMessage wrapper. HTML parse mode by default.

    Holds a default fan-out list of chat IDs but also exposes `send_to(chat_id, ...)`
    so callers can address a specific chat (useful for per-chat retry tracking).
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        bot_token: str,
        chat_ids: Iterable[str],
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> None:
        self._client = client
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._default_chat_ids: list[str] = [c for c in chat_ids if c]
        if not self._default_chat_ids:
            raise ValueError("TelegramNotifier requires at least one chat_id")
        self._parse_mode = parse_mode
        self._disable_preview = disable_web_page_preview

    @property
    def default_chat_ids(self) -> list[str]:
        return list(self._default_chat_ids)

    async def send_to(self, chat_id: str, text: str) -> bool:
        if len(text) > TELEGRAM_MAX:
            text = text[: TELEGRAM_MAX - 1] + "…"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": self._disable_preview,
        }
        try:
            resp = await self._client.post(self._url, json=payload)
            data = resp.json()
            if not data.get("ok"):
                logger.warning(
                    "telegram_send_failed chat_id=%s response=%s", chat_id, data
                )
                return False
            return True
        except Exception as exc:
            logger.warning("telegram_send_error chat_id=%s error=%s", chat_id, exc)
            return False

    async def send(self, text: str) -> dict[str, bool]:
        """Fan-out to all configured chat_ids. Returns {chat_id: ok}."""
        results: dict[str, bool] = {}
        for cid in self._default_chat_ids:
            results[cid] = await self.send_to(cid, text)
        return results
