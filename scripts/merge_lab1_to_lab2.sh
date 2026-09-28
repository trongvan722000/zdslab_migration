#!/usr/bin/env bash
# MERGE Lab 1 metadata INTO Lab 2 without touching what Lab 2 already has.
# Safe to re-run: matching is by UUID (objects) / username (users); existing Lab 2 objects are never deleted.
set -euo pipefail
cd "$(dirname "$0")/.."

TS=$(date +%Y%m%d_%H%M%S)
log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
quiet() { grep -vE 'Warning|warn|^\s*$' || true; }

log "0. Safety backup of Lab 2 metadata (Postgres) + snapshot of what Lab 2 has now"
docker exec postgres_lab2 sh -c \
  "pg_dump -U postgres --no-owner superset_meta > /backup/lab2_before_merge_${TS}.sql"
docker exec superset_lab2 python /app/fake_data/verify_merge.py snapshot 2>/dev/null > backup/lab2_before.json
ls -lh "backup/lab2_before_merge_${TS}.sql"

log "1. Export connections+datasets and dashboards+charts from Lab 1"
docker exec superset_lab1 sh -c \
  "superset export-datasources -f /tmp/datasources.zip && superset export-dashboards -f /tmp/dashboards.zip" 2>&1 | quiet | grep -i error || true
docker cp superset_lab1:/tmp/datasources.zip backup/datasources.zip
docker cp superset_lab1:/tmp/dashboards.zip backup/dashboards.zip

log "2. Add Lab 1 users missing from Lab 2 (matched by username; roles matched by role name)"
docker exec superset_lab2 python /app/fake_data/sync_users.py 2>&1 | quiet

log "3. Import into Lab 2 (runs Superset's import command in-process: no login, no HTTP)"
# Connection passwords are stored encrypted in Lab 1; Superset decrypts them, so nobody types N passwords.
# The plaintext file only exists inside the two containers for the duration of the import.
docker exec superset_lab1 python /app/fake_data/export_db_passwords.py /tmp/passwords.json 2>&1 | grep '^wrote' || true
docker cp superset_lab1:/tmp/passwords.json - | docker cp - superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/passwords.json
docker cp fake_data/import_bundle_direct.py superset_lab2:/tmp/import_bundle_direct.py
docker exec -u root superset_lab2 chown superset /tmp/import_bundle_direct.py
docker cp backup/datasources.zip superset_lab2:/tmp/datasources.zip
docker cp backup/dashboards.zip  superset_lab2:/tmp/dashboards.zip
for spec in dataset:datasources dashboard:dashboards; do
  docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json superset_lab2 \
    python /tmp/import_bundle_direct.py "${spec%%:*}" "/tmp/${spec#*:}.zip" admin 2>&1 \
    | grep -E "import \(direct\)|note:|cause|^   -" | cut -c1-200
done
docker exec superset_lab1 rm -f /tmp/passwords.json
docker exec superset_lab2 rm -f /tmp/passwords.json

log "4. Restore dashboard published/unpublished status (older exports do not carry it)"
docker exec superset_lab2 python /app/fake_data/sync_dashboard_published.py 2>&1 | quiet

log "5. Copy SQL Lab query history + saved queries (after connections exist: rows are re-mapped by user / connection name)"
docker exec superset_lab2 python /app/fake_data/sync_query_history.py 2>&1 | quiet

log "6. superset db upgrade + init, restart"
docker exec superset_lab2 superset db upgrade 2>&1 | quiet | tail -2
docker exec superset_lab2 superset init 2>&1 | quiet | tail -1
docker compose restart superset_lab2
until [ "$(docker inspect -f '{{.State.Health.Status}}' superset_lab2)" = healthy ]; do sleep 3; done

log "Done. Run scripts/verify.sh   (rollback file: backup/lab2_before_merge_${TS}.sql)"
