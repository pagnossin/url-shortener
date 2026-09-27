#!/bin/sh
set -e

case "$1" in
  web)
    exec uvicorn app.web:app \
      --host 0.0.0.0 --port "${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-1}" \
      --limit-concurrency "${WEB_MAX_REQUESTS:-500}" \
      --timeout-keep-alive 5 \
      --timeout-graceful-shutdown 20 \
      --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" \
      --no-access-log --no-server-header
    ;;
  --*)
    exec python -m app "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
