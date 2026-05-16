# hn-job-agent

Scans the latest HackerNews **"Ask HN: Who is hiring?"** thread, filters job postings to a narrow set of roles (Forward Deployed Engineer, ML Engineer, LLM / agentic systems) above a salary floor, and pushes matches to one or more Telegram chats.

## Filter rules

A posting is sent iff **all** hold:

1. **Role** — Forward Deployed Engineer, ML / AI Engineer, Research Engineer (ML), LLM engineer, applied AI, agentic systems, AI infra. Reject pure data engineering, generic SWE, frontend, devops, sales, product, internships.
2. **Salary** — either no salary is stated (pass), or the stated upper bound ≥ `MIN_SALARY_INR_LPA` (default 50 LPA INR). Conversion to INR uses live rates from `api.frankfurter.dev`; the threshold is pre-computed in each major currency and embedded in the LLM prompt so the model only extracts the raw amount + currency code — Python does the math.
3. **Location** — role is NOT US-only. US-headquartered companies hiring globally are fine; only postings that explicitly require existing US work authorization are filtered out.

## Setup

This agent is a member of the `agent-playground` uv workspace. Shared keys (`OPENROUTER_*`) live in `../.env` at the workspace root; agent-specific keys live in `./.env`. Per-key precedence: shell env > agent `.env` > workspace `.env`.

```bash
# from the workspace root
cd ~/Projects/agent_playground
cp .env.example .env                              # fill OPENROUTER_API_KEY (+ optional OPENROUTER_MODEL)
cd hn-job-agent
cp .env.example .env                              # fill TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
./run.sh
```

Schedule with cron / launchd. Daily runs are cheap (only new + previously-errored postings get classified).

### Multiple Telegram chats

`TELEGRAM_CHAT_IDS` accepts one or many comma-separated values:

```
TELEGRAM_CHAT_IDS=6682397806,-1001234567890
```

(The legacy singular name `TELEGRAM_CHAT_ID` is also accepted.) Each match is delivered to every configured chat, and per-chat delivery is tracked individually — if one chat succeeds and another fails, only the failed chat is retried on the next run.

### Getting a Telegram chat_id

1. Create a bot via [@BotFather](https://t.me/BotFather) → get `TELEGRAM_BOT_TOKEN`.
2. Send any message to your bot from your account.
3. `curl https://api.telegram.org/bot<TOKEN>/getUpdates` — your `chat_id` is at `result[0].message.chat.id`. For group chats, the id is negative (e.g. `-1001234567890`).

## State and dedup

`state/seen_ids.json` is a two-tier store, written atomically after every classification:

| Tier | Contents | Re-classified next run? | Re-sent next run? |
|---|---|---|---|
| `seen` | Postings that are *fully resolved* — either rejected by the filter, or successfully delivered to every configured chat. | No | No |
| `pending` | Postings that *were* classified and matched, but couldn't be delivered to one or more chats (Telegram error, or this run hit the per-run cap). Stores the formatted HTML message + remaining chat IDs. | **No** (skip LLM) | **Yes** (drain first thing next run) |

Postings that failed mid-classification (rate limit, model refusal) go to **neither** tier — they're retried fresh next run. This means a delivery failure never costs you another OpenRouter call.

Delete `state/seen_ids.json` to reset everything.

## Per-run cap

`MAX_NOTIFICATIONS_PER_RUN` caps the number of unique postings notified in a single run. Set to `0` to disable the cap and send every match each run. When the cap is hit, additional matches go to `pending` for delivery on the next run.

## Layout

```
hn-job-agent/
├── pyproject.toml             depends on `shared`
├── .env.example
├── run.sh                     cd here; uv sync; python -m hn_job_agent
├── state/seen_ids.json        runtime state (gitignored)
└── src/hn_job_agent/
    ├── config.py              pydantic-settings — loads ../.env then ./.env
    ├── hn.py                  HN Algolia thread lookup + Firebase comment fetch
    ├── classifier.py          OpenRouter prompt + JobVerdict schema
    ├── pipeline.py            orchestrator (drain pending → classify new → send)
    ├── state.py               atomic read/write of seen+pending
    └── __main__.py
```

Cross-agent utilities (Telegram, FX, OpenRouter call) live in `../shared/`.

## Choosing a model

Tested:

- `anthropic/claude-haiku-4.5` — reliable structured output, costs ~$0.10 / 300 postings, requires OpenRouter credits ≥ $10 to unlock per-minute / daily rate limits high enough for a first-run sweep.
- `openai/gpt-oss-120b:free` — zero-cost, no rate-limit walls once your account has ≥ $10 lifetime spend, but ~30% of postings need re-classification next run due to occasional empty / malformed responses.

Set via `OPENROUTER_MODEL` in either `.env`.

## Typical timeline

- **First run on a fresh thread** (~330 postings): ~10–70 minutes depending on chosen model and OpenRouter credits.
- **Daily runs after that**: ~5–15 minutes — just the previously-errored postings plus any new comments.
- **Monthly turnover** (when "(May 2026)" becomes "(June 2026)"): another big run, then back to daily.
