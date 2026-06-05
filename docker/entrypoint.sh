#!/usr/bin/env sh
set -eu

if command -v ollama >/dev/null 2>&1 && [ -n "${OLLAMA_MODEL:-}" ]; then
  ollama pull "$OLLAMA_MODEL" || true
fi

exec "$@"

