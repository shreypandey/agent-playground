# shared

Cross-agent utilities for `agent_playground` workspace members. Three small modules, each pure-async and stateless (state belongs in the calling agent).

## `shared.telegram` — `TelegramNotifier`

Thin wrapper around the Telegram Bot API's `sendMessage`. HTML parse mode by default.

```python
from shared import TelegramNotifier

notifier = TelegramNotifier(
    client,                              # httpx.AsyncClient
    bot_token="123456:ABC-...",
    chat_ids=["6682397806", "-100123..."],  # one or more
)

results = await notifier.send("<b>hello</b>")           # fan out to all chats
# {"6682397806": True, "-100123...": False}

ok = await notifier.send_to("6682397806", "<b>hi</b>")  # one chat only
```

`send_to` is what to use when you want per-chat retry tracking (so a posting that delivered to chat A but not chat B can be retried for B only).

## `shared.fx` — `FxTable`

Live INR-anchored exchange-rate table from [Frankfurter](https://frankfurter.dev). Optionally also pre-computes the threshold-in-each-currency for a given INR-LPA salary floor — useful when prompting an LLM to extract salary ranges without asking it to do arithmetic.

```python
from shared import get_fx_table

fx = await get_fx_table(
    client,
    min_salary_inr_lpa=50,       # optional: pre-compute thresholds
    fallback_usd_inr=83.0,       # used if Frankfurter is down
)

fx.to_inr_lpa(200_000, "USD")    # → e.g. 191.4 (LPA INR)
fx.rates_to_inr["EUR"]           # → e.g. 95.7 (INR per 1 EUR)
print(fx.prompt_table())         # drop directly into an LLM system prompt
```

Common currencies fetched in one call: USD, EUR, GBP, CAD, AUD, SGD, CHF, JPY, HKD, NZD, SEK, NOK, DKK, PLN, ZAR (+ INR base).

## `shared.openrouter` — `chat_json`

Single-shot chat completion with `response_format: json_schema`. Returns the parsed dict, or raises a typed error.

```python
from shared import chat_json, OpenRouterError, RetryableOpenRouterError

try:
    data = await chat_json(
        client,
        model="anthropic/claude-haiku-4.5",
        system="You are a strict JSON emitter.",
        user="Classify: ...",
        response_schema={"name": "MyResult", "strict": True, "schema": {...}},
        api_key=settings.openrouter_api_key,
    )
except OpenRouterError as e:
    ...  # logged and skipped — caller decides what to do
```

Behavior:
- **Retries** `429` and `5xx` automatically via [tenacity](https://github.com/jd/tenacity), honoring the server's `Retry-After` header when present, otherwise exponential backoff with jitter (capped at 30 s). Default 5 attempts.
- **Does not retry** permanent failures (`null_content`, malformed JSON, missing `choices`) — those raise `OpenRouterError` immediately so the caller can mark the item as failed instead of wasting more calls.
- `RetryableOpenRouterError` is a subclass of `OpenRouterError`, raised only when retries are exhausted.

## Adding to `shared/`

Move a utility here only when at least two workspace agents would import it. For single-consumer code, keep it inside the agent's own module — easier to evolve, no risk of breaking other agents.
