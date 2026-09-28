#!/usr/bin/env bash
# Verify the Lab 1 -> Lab 2 merge: nothing lost from Lab 2, everything from Lab 1 present,
# connections decrypt+connect, and every chart returns data for a migrated user.
set -uo pipefail
cd "$(dirname "$0")/.."
FAIL=0

echo "== 1. Names: Lab 1 vs Lab 2 (before / now)"
docker exec -i superset_lab2 python /app/fake_data/verify_merge.py check < backup/lab2_before.json 2>/dev/null || FAIL=1

echo; echo "== 2. Every connection in Lab 2 (decrypts password with SECRET_KEY, opens a connection)"
docker exec superset_lab2 python /app/fake_data/check_connections.py 2>/dev/null | grep '^   ' || FAIL=1

echo; echo "== 3. Charts as a migrated Lab 1 user (zds_alice) and as a pre-existing Lab 2 user (lab2_nam)"
docker exec superset_lab2 python /app/fake_data/smoke_test_api.py http://localhost:8088 zds_alice 'Passw0rd!' 2>&1 | tail -n +2 || FAIL=1
docker exec superset_lab2 python /app/fake_data/smoke_test_api.py http://localhost:8088 lab2_nam 'Lab2Passw0rd!' 2>&1 | head -1 || FAIL=1

[ "$FAIL" = 0 ] && echo -e "\nALL CHECKS PASSED" || { echo -e "\nSOME CHECKS FAILED"; exit 1; }
