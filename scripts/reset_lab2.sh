#!/usr/bin/env bash
# Put Lab 2 back to its "before merge" state: empty metadata, then its OWN users/connections/dashboards/history.
# Lab 1 and the data servers are not touched.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose stop superset_lab2
docker exec postgres_lab2 dropdb -U postgres superset_meta
docker exec postgres_lab2 createdb -U postgres -O superset superset_meta
docker compose start superset_lab2
printf 'waiting for superset_lab2 (db upgrade + init) '
until [ "$(docker inspect -f '{{.State.Health.Status}}' superset_lab2)" = healthy ]; do printf '.'; sleep 3; done; echo ' healthy'

docker exec superset_lab2 python /app/fake_data/seed_lab2_existing.py 2>&1 | grep -vE 'Warning|warn' | tail -9
docker exec superset_lab2 python /app/fake_data/seed_query_history.py lab2 2>&1 | grep -vE 'Warning|warn'
rm -f backup/* 2>/dev/null || true
