# agent-playground

A `uv` workspace for small, single-purpose AI agents that share LLM keys, a virtual environment, and a common utility library.

## Layout

```
agent_playground/
├── pyproject.toml          workspace root: shared deps + member list
├── .env                    shared LLM keys (gitignored)
├── .env.example
├── .venv/                  single shared venv (uv-managed)
├── uv.lock
│
├── shared/                 cross-agent utility library (workspace member)
│   ├── pyproject.toml
│   └── src/shared/
│       ├── telegram.py     async TelegramNotifier with multi-chat fan-out
│       ├── fx.py           live FX rates from Frankfurter + LLM-prompt helpers
│       └── openrouter.py   structured-JSON chat helper with tenacity retries
│
└── hn-job-agent/           first agent (workspace member)
    ├── pyproject.toml      depends on `shared`
    ├── .env                agent-specific config (gitignored)
    ├── .env.example
    ├── run.sh
    ├── state/seen_ids.json runtime state (gitignored)
    └── src/hn_job_agent/    ...
```

## Conventions

**Where things live.** Anything shared by multiple agents (LLM keys, deps, the `shared` library, the venv) belongs at the workspace root. Anything specific to one agent — its Telegram chat IDs, salary thresholds, classifier prompts, runtime state — belongs inside that agent's folder. Pre-existing sibling projects under `~/Projects/` are *not* members of this workspace and stay independent.

**Env override chain.** Each agent's `Settings` loads `../.env` then `./.env`, so an agent can override any workspace-level key in its own `.env`. Shell env always wins over both. This is how `hn-job-agent` pins its own `OPENROUTER_MODEL` while inheriting the shared `OPENROUTER_API_KEY` from the workspace root.

**Promoting to `shared/`.** Move a utility into `shared/` only when a second agent would use it. Don't pre-abstract — three near-duplicate lines beat one premature abstraction.

**State persistence.** Agents that produce notifications use a two-tier state file:
- `seen`: posting IDs that are fully resolved (rejected by filter, or successfully delivered).
- `pending`: posting IDs that have been classified and matched but haven't yet been delivered to every configured destination.

A run drains `pending` first (no LLM cost — just retried sends), then classifies anything not in either set. This means a delivery failure (wrong chat ID, Telegram outage, per-run cap) never wastes the OpenRouter call that produced the match.

## Quickstart

```bash
git clone https://github.com/shreypandey/agent-playground.git
cd agent-playground
cp .env.example .env                              # fill OPENROUTER_API_KEY
cd hn-job-agent && cp .env.example .env           # fill TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS
./run.sh
```

`run.sh` is a one-shot: it `uv sync`s the workspace and runs the agent once. Schedule via cron / launchd as you see fit. Daily runs are cheap because dedup keeps the work bounded to new postings + previously-errored ones.

## Adding a new agent

1. Create a new folder `agent_playground/<new-agent>/` with its own `pyproject.toml` (depend on `shared` if useful).
2. Add `"<new-agent>"` to both `[tool.uv.workspace] members` and `[project] dependencies` in the workspace root `pyproject.toml`.
3. Run `uv sync` at the workspace root.
4. Use `Settings(env_file=("../.env", ".env"))` so the agent picks up shared keys and can override per-agent.
5. Write a `run.sh` that `cd "${0:A:h}"` and `exec uv run python -m <module>`.

## Agents

- [`hn-job-agent`](./hn-job-agent/README.md) — surfaces matching jobs from HN's monthly "Who is hiring?" thread to Telegram.
