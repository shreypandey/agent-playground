# hn-job-agent

Scans the latest HackerNews **"Ask HN: Who is hiring?"** thread, filters job postings to a narrow set of roles (Forward Deployed Engineer, ML Engineer, LLM / agentic systems) above a salary floor, and pushes matches to Telegram.

## Filter rules

A posting is sent iff **all** hold:

1. **Role** — Forward Deployed Engineer, ML / AI Engineer, Research Engineer (ML), LLM engineer, applied AI, agentic systems, AI infra. Reject pure data-engineering, generic SWE, frontend, devops, sales, product, internships.
2. **Salary** — either no salary is stated (pass), or stated salary ≥ `MIN_SALARY_INR_LPA` (default 50 LPA INR).
3. **Location** — role is NOT US-only / does NOT require existing US work authorization. US-headquartered companies hiring globally are fine.

USD → INR (and EUR/GBP/CAD/AUD/SGD/CHF/JPY/HKD/...) conversion uses live rates from `api.frankfurter.dev` fetched on each run. The threshold is pre-computed in each currency and embedded in the LLM prompt so the model never does arithmetic — it only extracts the native amount + currency code, and Python converts.

## Setup

This agent is a uv workspace member. Shared keys (OpenRouter) live in `../.env` at the workspace root; agent-specific keys live in `./.env`. The agent `.env` overrides root keys for keys present in both.

```bash
# one-time, from the workspace root
cd ~/Projects/agent_playground
cp .env.example .env                      # fill OPENROUTER_API_KEY
cd hn-job-agent
cp .env.example .env                      # fill TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
./run.sh
```

Schedule via cron / launchd yourself.

### Getting a Telegram chat_id

1. Create a bot via [@BotFather](https://t.me/BotFather) → `TELEGRAM_BOT_TOKEN`.
2. Send any message to your bot.
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` — chat_id is at `result[0].message.chat.id`.

## How dedup works

`state/seen_ids.json` stores HN comment IDs already processed. Rejected matches are also marked seen so they aren't re-classified each run. If matches in a run exceed `MAX_NOTIFICATIONS_PER_RUN`, only the first N are sent and marked seen; the overflow is delivered on the next run.

Delete `state/seen_ids.json` to reset.

## Layout

```
hn-job-agent/
  pyproject.toml       depends on `shared` (workspace member)
  .env.example         agent-specific keys (Telegram, salary filter)
  run.sh               cd here; uv sync (workspace); python -m hn_job_agent
  state/seen_ids.json  dedup store
  src/hn_job_agent/
    config.py          loads ../.env then ./.env (later overrides earlier)
    hn.py              Algolia thread lookup + Firebase comment fetch
    classifier.py      OpenRouter prompt + JobVerdict schema (uses shared.openrouter)
    pipeline.py        orchestrator (uses shared.telegram, shared.fx)
    state.py           seen_ids.json atomic read/write
    __main__.py
```

Shared utilities (TelegramNotifier, FX table, OpenRouter JSON call) live at `../shared/src/shared/`.
