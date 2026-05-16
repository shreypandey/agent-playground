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
│       ├── openrouter.py   structured-JSON chat helper with tenacity retries
│       └── chatgpt_web.py  foreground ChatGPT web handoff helper
│
├── hn-job-agent/           HN hiring scanner (workspace member)
│   ├── pyproject.toml      depends on `shared`
│   ├── .env                agent-specific config (gitignored)
│   ├── .env.example
│   ├── run.sh
│   ├── state/seen_ids.json runtime state (gitignored)
│   └── src/hn_job_agent/    ...
│
├── fit-check-agent/        Chrome Native Messaging host for local profile fit checks
│   ├── profiles/           private profile directories (gitignored except .gitkeep)
│   ├── native-host.sh      executable used by Chrome Native Messaging
│   └── src/fit_check_agent/
│
└── fit-check-extension/    unpacked Chrome MV3 extension
```

## Conventions

**Where things live.** Anything shared by multiple agents (LLM keys, deps, the `shared` library, the venv) belongs at the workspace root. Anything specific to one agent — its Telegram chat IDs, salary thresholds, classifier prompts, runtime state — belongs inside that agent's folder. Pre-existing sibling projects under `~/Projects/` are *not* members of this workspace and stay independent.

**Env override chain.** Each agent's `Settings` loads `../.env` then `./.env`, so an agent can override any workspace-level key in its own `.env`. Shell env always wins over both. This is how `hn-job-agent` pins its own `OPENROUTER_MODEL` while inheriting the shared `OPENROUTER_API_KEY` from the workspace root.

**Promoting to `shared/`.** Move a utility into `shared/` only when a second agent would use it. Don't pre-abstract — three near-duplicate lines beat one premature abstraction.

**State persistence.** Agents that produce notifications use a two-tier state file:
- `seen`: posting IDs that are fully resolved (rejected by filter, or successfully delivered).
- `pending`: posting IDs that have been classified and matched but haven't yet been delivered to every configured destination.

A run drains `pending` first (no LLM cost — just retried sends), then classifies anything not in either set. This means a delivery failure (wrong chat ID, Telegram outage, per-run cap) never wastes the OpenRouter call that produced the match.

## Fit Check Quickstart

Use this path if you want the browser extension that sends the current product
page plus a local body/profile bundle to ChatGPT web.

Prerequisites:
- macOS. The ChatGPT handoff uses `open`, `pbcopy`, `osascript`, and `sips`.
- Chrome or a Chromium browser with Native Messaging support.
- [`uv`](https://docs.astral.sh/uv/) and Python 3.12 or newer.
- A working ChatGPT web login in the default browser.
- An OpenRouter key if you want LLM cleanup of noisy product text. Without it,
  the fit-check agent still runs with deterministic cleanup.

```bash
git clone https://github.com/shreypandey/agent-playground.git
cd agent-playground
uv sync
cp .env.example .env                              # fill OPENROUTER_API_KEY if using LLM cleanup

mkdir -p fit-check-agent/profiles/demo
cat > fit-check-agent/profiles/demo/measurements.md <<'EOF'
# Measurements
Height:
Chest:
Waist:
Hip:
Shoulder:
Sleeve:

# Fit preferences
Usual top size:
Preferred fit:
Avoid:
EOF

# Add at least one profile photo to fit-check-agent/profiles/demo/
```

Then:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click **Load unpacked** and select `fit-check-extension/`.
4. Copy the generated extension ID.
5. Install the native host:

```bash
cd fit-check-agent
cp .env.example .env
./install-native-host.sh <chrome-extension-id>
uv run fit-check list-profiles
```

Open a product page, click the Fit Check extension, select a profile, and click
**Analyze Outfit**. Keep the browser focused while ChatGPT opens and the agent
pastes profile/product images and the prompt.

See [`fit-check-agent`](./fit-check-agent/README.md) and
[`fit-check-extension`](./fit-check-extension/README.md) for details and
troubleshooting.

## HN Job Agent Quickstart

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
- [`fit-check-agent`](./fit-check-agent/README.md) + [`fit-check-extension`](./fit-check-extension/) — sends product pages and local profile bundles to ChatGPT web for visual fit checks.
