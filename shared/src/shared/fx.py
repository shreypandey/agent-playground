from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

COMMON_CURRENCIES = [
    "USD", "EUR", "GBP", "CAD", "AUD", "SGD", "CHF", "JPY", "HKD",
    "NZD", "SEK", "NOK", "DKK", "PLN", "ZAR",
]


@dataclass
class FxTable:
    """Live exchange-rate table anchored on INR.

    Use `get_fx_table()` to build. Provides:
      - rates_to_inr[CCY]: 1 unit of CCY = X INR
      - threshold_in_ccy[CCY]: a chosen INR-LPA threshold expressed in CCY/year
        (populated when `min_salary_inr_lpa` is passed to get_fx_table)
      - prompt_table(): a human-readable block to drop into LLM system prompts
    """

    rates_to_inr: dict[str, float] = field(default_factory=dict)
    threshold_in_ccy: dict[str, float] = field(default_factory=dict)
    source: str = "fallback"
    min_salary_inr_lpa: float = 0.0

    def threshold_inr(self) -> float:
        return self.min_salary_inr_lpa * 100_000.0

    def to_inr_lpa(self, amount: float, currency: str) -> float | None:
        rate = self.rates_to_inr.get(currency.upper())
        if rate is None:
            return None
        return amount * rate / 100_000.0

    def prompt_table(self) -> str:
        threshold_inr = self.threshold_inr()
        lines = [
            f"Salary threshold to pass: {self.min_salary_inr_lpa:.0f} LPA INR "
            f"(= ₹{threshold_inr:,.0f}/year).",
            "Threshold equivalents in major currencies (per year):",
        ]
        ordered = ["INR"] + [c for c in sorted(self.threshold_in_ccy) if c != "INR"]
        for ccy in ordered:
            if ccy not in self.threshold_in_ccy:
                continue
            amt = self.threshold_in_ccy[ccy]
            lines.append(f"  - {ccy}: {amt:,.0f} / year")
        return "\n".join(lines)


async def get_fx_table(
    client: httpx.AsyncClient,
    *,
    min_salary_inr_lpa: float = 0.0,
    fallback_usd_inr: float = 83.0,
    currencies: list[str] | None = None,
) -> FxTable:
    currencies = currencies or COMMON_CURRENCIES
    table = FxTable(source="fallback", min_salary_inr_lpa=min_salary_inr_lpa)
    threshold_inr = min_salary_inr_lpa * 100_000.0

    try:
        resp = await client.get(
            FRANKFURTER_URL,
            params={"base": "INR", "to": ",".join(currencies)},
        )
        resp.raise_for_status()
        data = resp.json()
        rates_to_inr: dict[str, float] = {"INR": 1.0}
        for ccy, ccy_per_inr in data.get("rates", {}).items():
            if ccy_per_inr and ccy_per_inr > 0:
                rates_to_inr[ccy] = 1.0 / ccy_per_inr
        table.rates_to_inr = rates_to_inr
        table.source = "frankfurter"
        logger.info(
            "fx_table_loaded source=frankfurter usd_inr=%.4f",
            rates_to_inr.get("USD", float("nan")),
        )
    except Exception as exc:
        logger.warning(
            "frankfurter_fetch_failed error=%s using_usd_fallback=%.4f",
            exc,
            fallback_usd_inr,
        )
        table.rates_to_inr = {"INR": 1.0, "USD": fallback_usd_inr}

    if threshold_inr > 0:
        table.threshold_in_ccy = {
            ccy: threshold_inr / rate for ccy, rate in table.rates_to_inr.items()
        }
    return table
