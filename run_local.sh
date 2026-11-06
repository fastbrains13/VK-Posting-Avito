#!/usr/bin/env bash
# Локальный запуск MVP v0: Django + воркер. PostgreSQL должен быть запущен.
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ -x ./.venv/bin/python ]]; then
  PYTHON="${PYTHON:-./.venv/bin/python}"
else
  PYTHON="${PYTHON:-python3}"
fi
mkdir -p run

start() {
  local name="$1" pidfile="run/$1.pid" logfile="run/$1.log"
  shift
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name уже запущен (pid $(cat "$pidfile"))"
    return 0
  fi
  nohup "$PYTHON" -u "$@" >"$logfile" 2>&1 &
  echo $! >"$pidfile"
  echo "$name запущен (pid $!), лог: $logfile"
}

start server manage.py runserver 127.0.0.1:8000 --noreload
start worker manage.py worker
echo "Админка: http://127.0.0.1:8000"
