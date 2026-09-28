"""Smoke-test a Superset instance through its REST API: login, list objects, run every chart.

    docker exec superset_lab2_mysql python /app/fake_data/../scripts/smoke_test_api.py   (see README)
    python scripts/smoke_test_api.py http://localhost:8090 zds_henry 'Passw0rd!'          (from host, needs requests)
"""
import json
import os
import sys

import requests

max_charts = int(os.environ.get("MAX_CHARTS", "0")) or None  # cap how many charts run (each one queries the data DB)
base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8088"
username = sys.argv[2] if len(sys.argv) > 2 else "admin"
password = sys.argv[3] if len(sys.argv) > 3 else "admin"

s = requests.Session()
r = s.post(f"{base}/api/v1/security/login",
           json={"username": username, "password": password, "provider": os.environ.get("AUTH_PROVIDER", "db"), "refresh": False})
r.raise_for_status()
s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
s.headers["X-CSRFToken"] = s.get(f"{base}/api/v1/security/csrf_token/").json()["result"]
s.headers["Referer"] = base
print(f"login {username}@{base}: OK")

q = "?q=" + json.dumps({"page_size": 100})
for res in ("database", "dataset", "chart", "dashboard"):
    print(f"  {res:<10} {s.get(f'{base}/api/v1/{res}/{q}').json()['count']}")

failed = 0
cols_q = "?q=" + json.dumps({"page_size": 100, "columns": ["id", "slice_name", "params", "datasource_id"]})
for chart in sorted(s.get(f"{base}/api/v1/chart/{cols_q}").json()["result"], key=lambda c: c["id"])[:max_charts]:
    params = json.loads(chart["params"] or "{}")
    columns = params.get("groupby") or ([params["x_axis"]] if params.get("x_axis") else [])
    payload = {
        "datasource": {"id": chart["datasource_id"], "type": "table"},
        "queries": [{"columns": columns, "metrics": ["count"], "row_limit": 1000}],
        "result_format": "json", "result_type": "full",
    }
    r = s.post(f"{base}/api/v1/chart/data", json=payload)
    body = r.json()
    ok = r.status_code == 200
    failed += not ok
    info = (f"rows={body['result'][0]['rowcount']}" if ok
            else f"HTTP {r.status_code} {str(body.get('message') or body)[:120]}")
    print(f"  chart #{chart['id']:<3} {chart['slice_name']:<26} {'OK  ' if ok else 'FAIL'} {info}")

sys.exit(1 if failed else 0)
