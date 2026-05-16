from __future__ import annotations

import asyncio
import logging

import httpx
from pydantic import BaseModel, ValidationError

from shared import FxTable, OpenRouterError, chat_json

from hn_job_agent.config import Settings
from hn_job_agent.hn import Posting

logger = logging.getLogger(__name__)

VERDICT_SCHEMA = {
    "name": "JobVerdict",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "role_match",
            "role_label",
            "salary_known",
            "salary_min_native",
            "salary_max_native",
            "salary_currency",
            "company",
            "location",
            "requires_us_presence",
            "one_line_summary",
            "reason",
        ],
        "properties": {
            "role_match": {"type": "boolean"},
            "role_label": {"type": ["string", "null"]},
            "salary_known": {"type": "boolean"},
            "salary_min_native": {"type": ["number", "null"]},
            "salary_max_native": {"type": ["number", "null"]},
            "salary_currency": {"type": ["string", "null"]},
            "company": {"type": ["string", "null"]},
            "location": {"type": ["string", "null"]},
            "requires_us_presence": {"type": "boolean"},
            "one_line_summary": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
}


class Verdict(BaseModel):
    role_match: bool
    role_label: str | None = None
    salary_known: bool
    salary_min_native: float | None = None
    salary_max_native: float | None = None
    salary_currency: str | None = None
    company: str | None = None
    location: str | None = None
    requires_us_presence: bool
    one_line_summary: str = ""
    reason: str = ""


def _system_prompt(fx_table: FxTable) -> str:
    return f"""You classify a single HackerNews "Who is hiring?" job posting.

Return a JSON object matching the provided schema. Be precise; never invent fields.
DO NOT perform currency conversion or arithmetic — extract the raw salary as stated
and the currency code. Python code will handle conversion using a live FX table.

ROLE MATCH RULES
  role_match=true ONLY if the posting is hiring for one of:
    - Forward Deployed Engineer (FDE) / Solutions Engineer with strong engineering bias
    - Machine Learning Engineer / AI Engineer / Applied AI / Research Engineer (ML)
    - LLM engineer, prompt engineer, agent / agentic systems engineer
    - AI infrastructure / ML platform / ML systems
  role_match=false for: pure data engineering without ML, generic backend/frontend SWE,
    devops/SRE, sales/marketing, product/PM, design, internships, recruiting agencies.
  If a posting lists multiple roles, role_match=true if AT LEAST ONE qualifies.
  role_label = the qualifying role title verbatim (or your best canonical name).

SALARY EXTRACTION (no math — just read what's there)
  If a salary is stated:
    salary_known=true.
    salary_currency = ISO 4217 3-letter code: "USD", "EUR", "GBP", "INR", "CAD",
      "AUD", "SGD", "CHF", "JPY", "HKD", "NZD", "SEK", "NOK", "DKK", "PLN", "ZAR".
    salary_min_native = lower bound of the range, in BASE UNITS per year.
      "$200K" → 200000.  "₹50L" or "50 LPA" → 5000000.  "€80k" → 80000.
      Multiply "K" by 1000, "L"/"lakh" by 100000, "Cr"/"crore" by 10000000.
      "$200/hr" → not annual; treat as unknown unless an annual figure is also given.
    salary_max_native = upper bound. If only one value, set BOTH min and max to it.
  If NO annual salary is stated (or only "competitive", equity-only, day-rate without
    annualizing), set: salary_known=false, salary_*_native=null, salary_currency=null.
  Equity / signing bonuses do NOT count as base salary.

REFERENCE — threshold equivalents in each currency (computed for you):
{fx_table.prompt_table()}

You don't need to compare salaries to these — Python will. The table is provided
only as a sanity check if you're unsure whether to extract a value at all.

LOCATION RULES
  requires_us_presence=true ONLY when the posting EXPLICITLY requires the candidate to
    be physically in the US OR to already hold US work authorization. Examples that
    trigger true: "US-only", "must be located in NYC/SF/etc", "no visa sponsorship",
    "US citizens or green-card holders only", "must be authorized to work in the US".
  US-headquartered company hiring remote/globally → false.
  Ambiguous / not stated → false (do NOT filter out unless explicit).

OTHER FIELDS
  company: company/team name if stated, else null.
  location: location string from the posting verbatim (e.g. "Remote, EU"), else null.
  one_line_summary: ≤ 140 chars, what they're building / stack.
  reason: 1–2 sentences explaining your role_match decision.
"""


DEFAULT_CONCURRENCY = 2


async def classify_one(
    client: httpx.AsyncClient,
    posting: Posting,
    fx_table: FxTable,
    settings: Settings,
    sem: asyncio.Semaphore,
) -> tuple[Posting, Verdict | None]:
    """Classify a single posting. Returns (posting, verdict_or_None).

    Wrapping the posting in the result lets callers use `asyncio.as_completed`
    and still know which posting each verdict corresponds to.
    """
    async with sem:
        try:
            parsed = await chat_json(
                client,
                model=settings.openrouter_model,
                system=_system_prompt(fx_table),
                user=(
                    f"HN posting id={posting.id}, author={posting.author}\n"
                    f"---\n{posting.text}"
                ),
                response_schema=VERDICT_SCHEMA,
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                title="hn-job-agent",
            )
            return posting, Verdict(**parsed)
        except (OpenRouterError, ValidationError) as exc:
            logger.warning(
                "classifier_failed posting_id=%s error=%s", posting.id, exc
            )
            return posting, None


def make_semaphore(concurrency: int = DEFAULT_CONCURRENCY) -> asyncio.Semaphore:
    return asyncio.Semaphore(concurrency)
