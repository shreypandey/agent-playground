#!/usr/bin/env zsh
set -euo pipefail

cd "${0:A:h}"

if [[ ! -f ../.env ]]; then
  print -u2 "[hn-job-agent] ../.env missing — copy ../.env.example to ../.env (shared keys live there)"
  exit 1
fi
if [[ ! -f .env ]]; then
  print -u2 "[hn-job-agent] .env missing — copy .env.example to .env (agent-specific keys)"
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "[hn-job-agent] uv not installed — see https://docs.astral.sh/uv/"
  exit 1
fi

uv sync --quiet
exec uv run python -m hn_job_agent
