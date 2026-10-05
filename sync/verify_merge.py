"""Compare source (Lab 1) and target (Lab 2) metadata by NAME, before/after a merge.

    docker exec superset_lab2 python /app/sync/verify_merge.py snapshot > backup/lab2_before.json
    docker exec -i superset_lab2 python /app/sync/verify_merge.py check < backup/lab2_before.json

`check` fails if (a) anything Lab 2 had before the merge is gone, or (b) anything from Lab 1 is missing in Lab 2.
"""
import json
import os
import sys

from sqlalchemy import create_engine, text

SRC_META_URI = os.environ.get(
    "SRC_META_URI", "mysql+mysqldb://superset:superset@mysql_lab1:3306/superset_meta?charset=utf8mb4"
)
QUERIES = {
    "users": "SELECT username FROM ab_user",
    "connections": "SELECT database_name FROM dbs",
    "datasets": "SELECT CONCAT(d.database_name, ' :: ', COALESCE(t.schema, ''), '.', t.table_name) "
                "FROM tables t JOIN dbs d ON d.id = t.database_id",
    "charts": "SELECT slice_name FROM slices",
    "dashboards": "SELECT dashboard_title FROM dashboards",
    # CASE..THEN 1 ELSE 0 (not COALESCE(published, 0) / bare boolean) so MySQL and Postgres render the same text:
    # MySQL has no real boolean (a raw bool concatenates as 1/0 already) but Postgres concatenates true/false.
    "dashboard status": "SELECT CONCAT(dashboard_title, ' :: published=', "
                         "CASE WHEN COALESCE(published, false) THEN 1 ELSE 0 END) FROM dashboards",
    "query history": "SELECT client_id FROM query",
    # {Q} = identifier quote char: "sql" is a reserved word in MySQL (needs `sql`) but not in Postgres,
    # where `sql` (backticks) is a syntax error instead - so the quote style must vary by dialect.
    "saved queries": "SELECT CONCAT(label, ' :: ', COALESCE({Q}sql{Q}, '')) FROM saved_query",
}


def names(uri):
    engine = create_engine(uri)
    quote = "`" if engine.dialect.name in ("mysql", "mariadb") else '"'
    with engine.connect() as c:
        return {k: sorted(r[0] for r in c.execute(text(q.format(Q=quote)))) for k, q in QUERIES.items()}


target = names(os.environ["META_DB_URI"])

if sys.argv[1] == "snapshot":
    print(json.dumps(target))
    sys.exit(0)

before = json.load(sys.stdin)
source = names(SRC_META_URI)
ok = True
print(f"{'':<14}{'lab1':>6}{'lab2 before':>13}{'lab2 now':>10}   lab1 missing in lab2 | lab2-before lost")
for k in QUERIES:
    missing = sorted(set(source[k]) - set(target[k]))
    lost = sorted(set(before.get(k, [])) - set(target[k]))
    ok &= not missing and not lost
    print(f"{k:<14}{len(source[k]):>6}{len(before.get(k, [])):>13}{len(target[k]):>10}   {len(missing)} | {len(lost)}")
    for m in missing:
        print(f"    MISSING from lab1: {m}")
    for m in lost:
        print(f"    LOST (was in lab2): {m}")
print("MERGE OK" if ok else "MERGE INCOMPLETE")
sys.exit(0 if ok else 1)
