from __future__ import annotations

import asyncio
import html as html_lib
import logging
from dataclasses import dataclass

import httpx

from shared import FxTable, TelegramNotifier, get_fx_table

from hn_job_agent import classifier, hn, state
from hn_job_agent.classifier import Verdict
from hn_job_agent.config import Settings
from hn_job_agent.hn import Posting

logger = logging.getLogger(__name__)


@dataclass
class SalaryConverted:
    known: bool
    min_inr_lpa: float | None
    max_inr_lpa: float | None
    native_str: str | None
    currency_unsupported: bool


def convert_salary(verdict: Verdict, fx_table: FxTable) -> SalaryConverted:
    if (
        not verdict.salary_known
        or verdict.salary_currency is None
        or verdict.salary_min_native is None
    ):
        return SalaryConverted(False, None, None, None, False)

    ccy = verdict.salary_currency.upper()
    lo = verdict.salary_min_native
    hi = verdict.salary_max_native or lo
    min_lpa = fx_table.to_inr_lpa(lo, ccy)
    max_lpa = fx_table.to_inr_lpa(hi, ccy)

    if lo == hi:
        native = f"{ccy} {lo:,.0f}/yr"
    else:
        native = f"{ccy} {lo:,.0f}–{hi:,.0f}/yr"

    if min_lpa is None or max_lpa is None:
        return SalaryConverted(False, None, None, native, True)

    return SalaryConverted(True, min_lpa, max_lpa, native, False)


def _esc(s: str | None) -> str:
    return html_lib.escape(s) if s else ""


def _salary_line(sc: SalaryConverted) -> str:
    if sc.known:
        lo = sc.min_inr_lpa or 0.0
        hi = sc.max_inr_lpa or 0.0
        if abs(hi - lo) < 0.5:
            inr_str = f"{lo:.0f} LPA INR"
        else:
            inr_str = f"{lo:.0f}–{hi:.0f} LPA INR"
        return f"💰 {inr_str} ({_esc(sc.native_str)})"
    if sc.currency_unsupported and sc.native_str:
        return f"💰 {_esc(sc.native_str)} (no FX rate)"
    return "💰 Salary: not stated"


def format_message(posting: Posting, verdict: Verdict, sc: SalaryConverted) -> str:
    role = _esc(verdict.role_label) or "Role"
    company = _esc(verdict.company) or "?"
    location = _esc(verdict.location) or "—"
    summary = _esc(verdict.one_line_summary)
    lines = [
        f"<b>{role}</b> @ {company}",
        _salary_line(sc),
        f"📍 {location}",
    ]
    if summary:
        lines.append(summary)
    lines.append("")
    lines.append(f'<a href="{posting.hn_url}">View on HN</a>')
    return "\n".join(lines)


def _matches(verdict: Verdict, sc: SalaryConverted, settings: Settings) -> bool:
    if not verdict.role_match:
        return False
    if verdict.requires_us_presence:
        return False
    if not sc.known:
        return True
    upper = sc.max_inr_lpa or sc.min_inr_lpa or 0.0
    return upper >= settings.min_salary_inr_lpa


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    settings = Settings()
    seen, pending = state.load(settings.state_file)
    state.reconcile_pending(pending, settings.telegram_chat_ids)
    logger.info(
        "state_loaded seen=%d pending=%d chat_ids=%d",
        len(seen), len(pending), len(settings.telegram_chat_ids),
    )

    timeout = httpx.Timeout(settings.request_timeout_seconds)
    limits = httpx.Limits(max_connections=20)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        fx_table = await get_fx_table(
            client,
            min_salary_inr_lpa=settings.min_salary_inr_lpa,
            fallback_usd_inr=settings.usd_to_inr_fallback,
        )
        postings = await hn.fetch_latest_hiring_postings(client, settings)
        new = [p for p in postings if p.id not in seen and p.id not in pending]
        logger.info(
            "new_postings=%d pending=%d (total_in_thread=%d)",
            len(new), len(pending), len(postings),
        )

        notifier = TelegramNotifier(
            client,
            bot_token=settings.telegram_bot_token,
            chat_ids=settings.telegram_chat_ids,
        )

        sent_postings = 0
        rejected = 0
        overflow = 0
        errors = 0
        per_chat_fails = 0
        # cap <= 0 means unlimited
        cap = settings.max_notifications_per_run
        capped = cap > 0

        async def deliver(pid: str, entry: state.PendingEntry) -> bool:
            """Attempt delivery to every chat in entry.chat_ids. Mutates entry to
            drop succeeded chats. Returns True iff all chats received the message.
            """
            nonlocal per_chat_fails
            remaining: list[str] = []
            for cid in entry.chat_ids:
                ok = await notifier.send_to(cid, entry.html)
                await asyncio.sleep(0.5)
                if ok:
                    continue
                remaining.append(cid)
                per_chat_fails += 1
            entry.chat_ids = remaining
            return not remaining

        # 1. Drain pending queue first — already classified, just retry sends.
        for pid in list(pending.keys()):
            if capped and sent_postings >= cap:
                break
            entry = pending[pid]
            fully_delivered = await deliver(pid, entry)
            sent_postings += 1  # counts the posting attempt, not per-chat sends
            if fully_delivered:
                seen.add(pid)
                del pending[pid]
            state.save(settings.state_file, seen, pending)

        # 2. Classify new postings.
        if new:
            sem = classifier.make_semaphore()
            tasks = [
                asyncio.create_task(
                    classifier.classify_one(client, p, fx_table, settings, sem)
                )
                for p in new
            ]
            try:
                for fut in asyncio.as_completed(tasks):
                    posting, verdict = await fut
                    if verdict is None:
                        errors += 1
                        continue
                    sc = convert_salary(verdict, fx_table)
                    if not _matches(verdict, sc, settings):
                        seen.add(posting.id)
                        rejected += 1
                        state.save(settings.state_file, seen, pending)
                        continue
                    html = format_message(posting, verdict, sc)
                    entry = state.PendingEntry(
                        html=html, chat_ids=list(settings.telegram_chat_ids)
                    )
                    if capped and sent_postings >= cap:
                        pending[posting.id] = entry
                        overflow += 1
                        state.save(settings.state_file, seen, pending)
                        continue
                    fully_delivered = await deliver(posting.id, entry)
                    sent_postings += 1
                    if fully_delivered:
                        seen.add(posting.id)
                    else:
                        pending[posting.id] = entry
                    state.save(settings.state_file, seen, pending)
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()

        logger.info(
            "run_summary sent_postings=%d rejected=%d overflow=%d "
            "per_chat_fails=%d classifier_errors=%d pending_now=%d",
            sent_postings, rejected, overflow, per_chat_fails, errors, len(pending),
        )

    state.save(settings.state_file, seen, pending)
