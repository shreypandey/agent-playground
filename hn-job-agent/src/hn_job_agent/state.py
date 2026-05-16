from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PendingEntry:
    """A classified, match-eligible posting awaiting delivery to one or more chats."""

    html: str
    chat_ids: list[str] = field(default_factory=list)  # chats still owed a delivery

    def to_json(self) -> dict:
        return {"html": self.html, "chat_ids": list(self.chat_ids)}

    @classmethod
    def from_json(cls, raw: object) -> "PendingEntry":
        # Legacy: a plain string from before multi-chat support — defaults to all
        # current chat_ids at load time (handled by caller).
        if isinstance(raw, str):
            return cls(html=raw, chat_ids=[])
        if isinstance(raw, dict):
            return cls(
                html=str(raw.get("html", "")),
                chat_ids=list(raw.get("chat_ids", [])),
            )
        raise TypeError(f"bad pending entry: {type(raw)}")


def load(path: Path) -> tuple[set[str], dict[str, PendingEntry]]:
    """Return (seen, pending).

    - `seen`: posting IDs fully resolved (rejected by filter, or delivered to all chats).
    - `pending`: posting_id → PendingEntry for matches still owed to some chat(s).
    """
    if not path.exists():
        return set(), {}
    try:
        data = json.loads(path.read_text())
        seen = set(data.get("seen", []))
        pending = {
            pid: PendingEntry.from_json(v)
            for pid, v in (data.get("pending") or {}).items()
        }
        return seen, pending
    except Exception as exc:
        logger.warning(
            "state_load_failed path=%s error=%s — starting fresh", path, exc
        )
        return set(), {}


def save(path: Path, seen: set[str], pending: dict[str, PendingEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seen": sorted(seen),
        "pending": {pid: e.to_json() for pid, e in pending.items()},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".seen-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def reconcile_pending(
    pending: dict[str, PendingEntry], configured_chat_ids: list[str]
) -> None:
    """In-place: ensure every pending entry's chat_ids list reflects the current config.

    - Legacy entries (chat_ids == []) get the full current set assigned.
    - Entries with chat_ids that include chats no longer configured: drop those.
    - Entries that end up with no remaining chats are dropped from pending entirely.
    """
    current = set(configured_chat_ids)
    drop: list[str] = []
    for pid, entry in pending.items():
        if not entry.chat_ids:
            entry.chat_ids = list(configured_chat_ids)
            continue
        entry.chat_ids = [c for c in entry.chat_ids if c in current]
        if not entry.chat_ids:
            drop.append(pid)
    for pid in drop:
        del pending[pid]
