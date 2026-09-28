"""Create real SQL Lab history + saved queries in Lab 1 by running queries through the REST API
as different users (so the `query` and `saved_query` tables get realistic rows).

    docker exec superset_lab1 python /app/fake_data/seed_query_history.py
    docker exec superset_lab2 python /app/fake_data/seed_query_history.py lab2   # Lab 2's own history
"""
import json
import os
import random
import string
import sys

import requests

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
PASSWORD = "Passw0rd!"

# (username, database_name, schema, sql)
QUERIES = [
    ("admin", "MySQL - Sales", "sales", "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"),
    ("admin", "MySQL - Sales", "sales", "SELECT sku, SUM(qty) AS qty FROM order_items GROUP BY sku ORDER BY qty DESC LIMIT 10"),
    ("zds_henry", "MySQL - CRM", "crm", "SELECT city, COUNT(*) AS customers FROM customers GROUP BY city"),
    ("zds_henry", "MySQL - CRM", "crm", "SELECT priority, status, COUNT(*) FROM tickets GROUP BY priority, status"),
    ("zds_henry", "Postgres - Finance", "public", "SELECT currency, ROUND(SUM(total), 2) AS total FROM invoices GROUP BY currency"),
    ("zds_henry", "Postgres - Finance", "public", "SELECT method, COUNT(*) FROM payments GROUP BY method"),
    ("zds_henry", "Postgres - Warehouse", "dw", "SELECT region, ROUND(SUM(revenue), 2) FROM dw.fact_revenue GROUP BY region"),
    ("zds_henry", "Postgres - Marketing", "public", "SELECT channel, ROUND(SUM(budget), 2) FROM campaigns GROUP BY channel"),
    ("admin", "Postgres - Marketing", "public", "SELECT campaign_id, COUNT(*) AS clicks FROM ad_clicks GROUP BY campaign_id ORDER BY clicks DESC LIMIT 5"),
    ("admin", "MySQL - Sales", "sales", "SELECT COUNT(*) FROM orders WHERE order_date >= '2026-03-01'"),
    # deliberately broken: history also keeps failed queries
    ("admin", "MySQL - Sales", "sales", "SELECT * FROM table_that_does_not_exist"),
]

# (username, database_name, schema, label, sql)
SAVED = [
    ("admin", "MySQL - Sales", "sales", "Orders by status", "SELECT status, COUNT(*) FROM orders GROUP BY status"),
    ("zds_henry", "Postgres - Finance", "public", "Invoice total by currency", "SELECT currency, SUM(total) FROM invoices GROUP BY currency"),
    ("admin", "Postgres - Marketing", "public", "Top campaigns by clicks", "SELECT campaign_id, COUNT(*) FROM ad_clicks GROUP BY 1 ORDER BY 2 DESC LIMIT 5"),
]


if len(sys.argv) > 1 and sys.argv[1] == "lab2":
    # Lab 2's OWN pre-existing history (used to test that the merge keeps it)
    PASSWORD = "Lab2Passw0rd!"
    QUERIES = [
        ("lab2_hung", "Lab2 - Legacy Sales", "sales", "SELECT status, COUNT(*) FROM orders GROUP BY status"),
        ("lab2_hung", "Lab2 - Legacy Finance", "public", "SELECT currency, COUNT(*) FROM invoices GROUP BY currency"),
        ("admin", "Lab2 - Legacy Sales", "sales", "SELECT COUNT(*) FROM orders"),
    ]
    SAVED = [
        ("lab2_hung", "Lab2 - Legacy Sales", "sales", "Lab2 orders count", "SELECT COUNT(*) FROM orders"),
    ]


def session(user, pwd):
    s = requests.Session()
    r = s.post(f"{BASE}/api/v1/security/login",
               json={"username": user, "password": pwd, "provider": "db", "refresh": False})
    r.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    s.headers["X-CSRFToken"] = s.get(f"{BASE}/api/v1/security/csrf_token/").json()["result"]
    s.headers["Referer"] = BASE
    return s


def main():
    admin = session("admin", "admin")
    dbs = {d["database_name"]: d["id"]
           for d in admin.get(f"{BASE}/api/v1/database/?q=" + json.dumps({"page_size": 100})).json()["result"]}
    sessions = {}

    def as_user(u):
        if u not in sessions:
            sessions[u] = session(u, "admin" if u == "admin" else PASSWORD)
        return sessions[u]

    for user, db, schema, sql in QUERIES:
        cid = "".join(random.choices(string.ascii_letters + string.digits, k=11))
        r = as_user(user).post(f"{BASE}/api/v1/sqllab/execute/", json={
            "client_id": cid, "database_id": dbs[db], "schema": schema, "sql": sql,
            "runAsync": False, "select_as_cta": False, "queryLimit": 1000,
            "tab": f"{user}-tab", "sql_editor_id": f"editor-{user}",
        })
        print(f"  query  {user:<10} {db:<22} HTTP {r.status_code}  {sql[:50]}")

    for user, db, schema, label, sql in SAVED:
        r = as_user(user).post(f"{BASE}/api/v1/saved_query/", json={
            "db_id": dbs[db], "schema": schema, "label": label, "sql": sql,
        })
        print(f"  saved  {user:<10} {label:<28} HTTP {r.status_code}")


if __name__ == "__main__":
    sys.exit(main())
