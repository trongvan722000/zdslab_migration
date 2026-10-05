"""Check that migrated SQL still works in THIS Superset, WITHOUT running it: each statement is sent as `EXPLAIN <sql>`.

EXPLAIN makes the data server parse the SQL and resolve every table/column/permission (so a wrong connection, missing
schema, wrong password or missing grant fails here), but no data is read and nothing is written. Only SELECT/WITH
statements are checked; INSERT/UPDATE/DDL and Jinja-templated SQL are reported as SKIP and never sent.
Each connection is opened ONCE first: if that fails (wrong password, `Access denied for user@host` because the data
server does not allow this host's IP yet, ...) its queries are counted as CONN, not checked and not FAIL. Fix the
connection (check_connections.py) and run again.

    docker exec superset_lab2 python /app/sync/check_queries.py saved             # every saved query
    docker exec superset_lab2 python /app/sync/check_queries.py history 100       # 100 latest distinct successful queries
    docker exec superset_lab2 python /app/sync/check_queries.py history 5 --per-connection   # 5 latest per connection

A saved "scratchpad" (several statements, some without ';', each run alone in SQL Lab by highlighting it) cannot be
checked as a whole: when it fails with a SYNTAX error and has more SELECT/WITH lines at column 0 (outside parentheses)
than ';'-separated statements, it is reported as SKIP (scratchpad), not FAIL.

Options:
    --full-sql         print the WHOLE SQL of every FAIL (default: first 300 characters)
    --report FILE      also write every result to FILE (JSON), to compare with the other lab
    --compare FILE     report of the OTHER lab (from --report): list items that are OK there but FAIL here.
                       Items are matched by saved_query.uuid / query.client_id (both kept by the migration), not id.
                       In history mode the SAME queries as in that report are checked (not this lab's latest N).
    --per-connection   history: take N per connection instead of N overall

Compare Lab 1 (runs on 2.1.x too) with Lab 2. A FAIL in BOTH labs is in the SQL itself (e.g. a saved "scratchpad" of
several SELECTs without ';', run one at a time in SQL Lab by highlighting), not a migration problem:

    docker exec superset_lab1 python /app/sync/check_queries.py saved --report /tmp/rep_lab1.json > /dev/null 2>&1
    docker cp superset_lab1:/tmp/rep_lab1.json - | docker cp - superset_lab2:/tmp/
    docker exec superset_lab2 python /app/sync/check_queries.py saved --full-sql --compare /tmp/rep_lab1.json 2>&1 | grep '^check'

Output lines start with "check" (grep for them: stdout also carries Superset's own log lines). Exit code 1 if any FAIL
(CONN does not count: it is a connection problem, not a SQL problem).
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict

import sqlparse

from superset.app import create_app

ap = argparse.ArgumentParser()
ap.add_argument("mode", nargs="?", default="saved", choices=["saved", "history"])
ap.add_argument("n", nargs="?", type=int, default=100, help="history: how many latest queries")
ap.add_argument("--per-connection", action="store_true")
ap.add_argument("--full-sql", action="store_true")
ap.add_argument("--report")
ap.add_argument("--compare")
args = ap.parse_args()
mode, n_latest = args.mode, args.n
STMT_START = re.compile(r"(select|with)\b", re.IGNORECASE)
EXPLAIN = {"oracle": "EXPLAIN PLAN FOR ", "druid": "EXPLAIN PLAN FOR "}  # everything else: "EXPLAIN "
NO_EXPLAIN = {"mssql"}


def engine_ctx(d, schema=None):
    # 2.1.x: get_sqla_engine_with_context(); 3.x+: get_sqla_engine() is itself the context manager
    return (getattr(d, "get_sqla_engine_with_context", None) or d.get_sqla_engine)(schema=schema)


def short(e):
    return f"{type(e).__name__}: {' '.join(str(e).split())[:180]}"


def print_sql(sql):
    if args.full_sql:
        for line in sql.strip().splitlines():
            print(f"check      | {line.rstrip()}", flush=True)
        print("check      +" + "-" * 100, flush=True)
    else:
        print(f"check      sql: {' '.join(sql.split())[:300]}", flush=True)


def top_level_starts(sql):
    """Lines starting (at column 0) with SELECT/WITH outside any parentheses, quotes and comments."""
    n, depth, i, line_start = 0, 0, 0, True
    while i < len(sql):
        c = sql[i]
        if line_start and depth == 0 and STMT_START.match(sql, i):
            n += 1
        line_start = c == "\n"
        if c in "'\"`":
            end = sql.find(c, i + 1)
            i = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith("--", i) or (c == "#" and sql[i + 1:i + 2] in ("", " ", "\t", "\n")):  # not PG's #>> / #>
            end = sql.find("\n", i)
            i = len(sql) if end < 0 else end
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        depth += (c == "(") - (c == ")")
        i += 1
    return n


def is_scratchpad(sql, stmts):
    return top_level_starts(sql) > len(stmts)


def statements(sql):
    """SELECT/WITH statements to check, or a reason to skip the whole item."""
    if "{{" in sql or "{%" in sql:
        return None, "Jinja template"
    out = []
    for stmt in sqlparse.split(sql):
        body = sqlparse.format(stmt, strip_comments=True).strip().rstrip(";").strip()
        if not body:
            continue
        if body.split(None, 1)[0].upper() not in ("SELECT", "WITH"):
            return None, f"not a SELECT ({body.split(None, 1)[0].upper()})"
        out.append(body)
    return (out, None) if out else (None, "empty")


app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database
    from superset.models.sql_lab import Query, SavedQuery

    dbs = {d.id: d for d in db.session.query(Database)}
    items = []  # (key, label, database_id, schema, sql); key is the same in both labs
    if mode == "saved":
        for q in db.session.query(SavedQuery).order_by(SavedQuery.id):
            items.append((str(q.uuid), f"saved #{q.id} {q.label or ''}"[:50], q.db_id, q.schema, q.sql or ""))
    elif args.compare:  # history: exactly the queries the other lab checked
        with open(args.compare) as f:
            wanted = list(json.load(f))
        for i in range(0, len(wanted), 500):
            for q in db.session.query(Query).filter(Query.client_id.in_(wanted[i:i + 500])):
                items.append((q.client_id, f"query {q.client_id}", q.database_id, q.schema, q.sql or ""))
    else:  # history: latest successful queries, identical SQL counted once
        seen, taken = set(), Counter()
        rows = db.session.query(Query).filter(Query.status == "success").order_by(Query.start_time.desc())
        for q in rows.yield_per(1000):
            key = (q.database_id, (q.sql or "").strip())
            group = q.database_id if args.per_connection else None
            if key in seen or taken[group] >= n_latest:
                continue
            seen.add(key)
            taken[group] += 1
            items.append((q.client_id, f"query {q.client_id}", q.database_id, q.schema, q.sql or ""))
            if not args.per_connection and taken[None] >= n_latest:
                break

    # Open each connection used by the items once; the ones that fail are skipped as a whole (CONN).
    conn_error = {}
    for db_id in sorted({i[2] for i in items if i[2] in dbs}):
        try:
            with engine_ctx(dbs[db_id]) as eng:
                eng.connect().close()
        except Exception as e:  # noqa: BLE001
            conn_error[db_id] = short(e)

    result = defaultdict(Counter)
    for db_id, err in conn_error.items():
        n = sum(1 for i in items if i[2] == db_id)
        result[dbs[db_id].database_name]["CONN"] += n
        print(f"check CONN | {dbs[db_id].database_name:<30} | {n} item(s) NOT checked: cannot connect | {err}", flush=True)

    report = {}  # key -> {status, connection, label, error, sql}
    for key, label, db_id, schema, sql in items:
        d = dbs.get(db_id)
        name = d.database_name if d else f"<db_id {db_id} missing>"
        if db_id in conn_error:
            report[key] = {"status": "CONN", "connection": name, "label": label, "error": conn_error[db_id], "sql": sql}
            continue
        stmts, why = statements(sql)
        if d is None:
            status = "FAIL no such connection in this Superset"
        elif why or d.backend in NO_EXPLAIN:
            status = f"SKIP {why or 'EXPLAIN not supported by ' + d.backend}"
        else:
            try:
                with engine_ctx(d, schema) as eng:
                    raw = eng.raw_connection()  # raw DBAPI cursor: no bind-param parsing of ':' or '%' in the SQL
                    try:
                        cur = raw.cursor()
                        for s in stmts:
                            cur.execute(EXPLAIN.get(d.backend, "EXPLAIN ") + s)
                            cur.fetchall()
                    finally:
                        raw.close()
                status = "OK"
            except Exception as e:  # noqa: BLE001
                status = f"FAIL {short(e)}"
                if "syntax" in str(e).lower() and is_scratchpad(sql, stmts):
                    status = "SKIP scratchpad: several statements without ';' (run one by one in SQL Lab)"
        result[name][status.split()[0]] += 1
        report[key] = {"status": status.split()[0], "connection": name, "label": label, "error": status[5:], "sql": sql}
        print(f"check {status.split()[0]:<4} | {name:<30} | {label:<50} | {status[5:] if status != 'OK' else ''}", flush=True)
        if status.startswith("FAIL"):
            print_sql(sql)

print("check ---- summary per connection (OK / FAIL / SKIP / CONN = not checked, cannot connect) ----")
for name in sorted(result):
    c = result[name]
    print(f"check {name:<30} OK {c['OK']:>4}  FAIL {c['FAIL']:>4}  SKIP {c['SKIP']:>4}  CONN {c['CONN']:>4}")
total = Counter()
for c in result.values():
    total.update(c)
print(f"check TOTAL {len(items)} item(s): OK {total['OK']}, FAIL {total['FAIL']}, SKIP {total['SKIP']}, "
      f"CONN {total['CONN']} (in {len(conn_error)} connection(s) that cannot connect)")

if args.report:
    with open(args.report, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"check report written: {args.report}")

if args.compare:
    with open(args.compare) as f:
        other = json.load(f)
    regressions = [(k, other[k], r) for k, r in report.items() if r["status"] == "FAIL" and other.get(k, {}).get("status") == "OK"]
    both_fail = sum(1 for k, r in report.items() if r["status"] == "FAIL" and other.get(k, {}).get("status") == "FAIL")
    other_conn = sum(1 for k, r in report.items() if r["status"] == "FAIL" and other.get(k, {}).get("status") == "CONN")
    missing = [k for k, o in other.items() if k not in report]
    print("check ==== COMPARE with " + args.compare + " ====")
    print(f"check FAIL in both labs (same error in the other lab: not caused by the migration - SQL or data-server permission): {both_fail}")
    print(f"check FAIL here, other lab could not connect (cannot compare): {other_conn}")
    print(f"check OK in other lab but FAIL here (MIGRATION PROBLEM, look at these): {len(regressions)}")
    for k, o, r in regressions:
        print(f"check REGR | {r['connection']:<30} | {r['label']:<50} | {r['error']}")
        print_sql(r["sql"])
    print(f"check in other lab but MISSING here: {len(missing)}")
    for k in missing:
        print(f"check MISS | {other[k]['connection']:<30} | {other[k]['label']}")

sys.exit(1 if total["FAIL"] else 0)
