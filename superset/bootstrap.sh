#!/usr/bin/env bash
set -e

echo "[$LAB_NAME] superset db upgrade"
superset db upgrade

echo "[$LAB_NAME] create admin (skipped if exists)"
superset fab create-admin \
  --username admin --firstname Admin --lastname "$LAB_NAME" \
  --email "admin@$LAB_NAME.local" --password admin || true

echo "[$LAB_NAME] superset init"
superset init

echo "[$LAB_NAME] starting web server"
exec gunicorn --bind 0.0.0.0:8088 --workers 1 --threads 4 --worker-class gthread --timeout 120 \
  "superset.app:create_app()"
