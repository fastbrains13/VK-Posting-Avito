#!/usr/bin/env bash
# Остановить локальные процессы MVP v0. PostgreSQL остаётся запущенным.
set -Eeuo pipefail
cd "$(dirname "$0")"
for name in server worker; do
  pidfile="run/$name.pid"
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && echo "$name остановлен (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
done
