#!/usr/bin/env zsh
set -euo pipefail

cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "[fit-check-agent] uv not found; install uv or add it to PATH"
  exit 1
fi

exec uv run python -m fit_check_agent.native_host
