#!/usr/bin/env bash
# Portable Aider + local Ollama launcher, written by `/local-models`'s
# confirmed-stack autowire (local-models-confirmed-stack-autowire). Refreshes
# the guest-reachable OLLAMA_API_BASE in .env before handing off to `aider` —
# gateway IPs churn after `wsl --shutdown` / reboot, so a stale launcher is
# exactly how the Connection-refused footgun comes back. `.env` alone (not
# this launcher) is the actual bare-`aider` fix; this script is optional
# convenience for operators who prefer one command over two.
set -euo pipefail

MODEL="${AIDER_OLLAMA_MODEL:-}"
PROJECT_ROOT="$(pwd)"

# The .env writer ships to .anchor/scripts/ in a scaffolded consumer project,
# or scripts/ in the Anchor source tree itself.
if [ -f "$PROJECT_ROOT/.anchor/scripts/write_aider_env.py" ]; then
  WRITER="$PROJECT_ROOT/.anchor/scripts/write_aider_env.py"
elif [ -f "$PROJECT_ROOT/scripts/write_aider_env.py" ]; then
  WRITER="$PROJECT_ROOT/scripts/write_aider_env.py"
else
  echo "warning: write_aider_env.py not found under .anchor/scripts/ or scripts/ — .env may be stale" >&2
  WRITER=""
fi

if [ -n "$WRITER" ]; then
  python3 "$WRITER" --root "$PROJECT_ROOT" || echo "warning: .env refresh failed; continuing with existing .env" >&2
fi

if [ -n "$MODEL" ]; then
  exec aider --model "ollama_chat/$MODEL" "$@"
fi
exec aider "$@"
