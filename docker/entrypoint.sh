#!/usr/bin/env sh
set -eu

if [ "${ADDA_PULL_OLLAMA:-1}" = "1" ] && [ -n "${OLLAMA_MODEL:-}" ] && [ -n "${OLLAMA_HOST:-}" ]; then
  echo "Ensuring Ollama model is available: ${OLLAMA_MODEL}"
  tries=0
  until curl -fsS "${OLLAMA_HOST%/}/api/tags" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 30 ]; then
      echo "Ollama did not become ready; continuing without model pull" >&2
      break
    fi
    sleep 2
  done
  if curl -fsS "${OLLAMA_HOST%/}/api/tags" >/dev/null 2>&1; then
    curl -fsS "${OLLAMA_HOST%/}/api/pull" \
      -H "Content-Type: application/json" \
      -d "{\"name\":\"${OLLAMA_MODEL}\",\"stream\":false}" >/dev/null || true
  fi
fi

exec "$@"
