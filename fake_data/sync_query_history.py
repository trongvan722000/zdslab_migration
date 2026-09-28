"""Copy SQL Lab query history (`query`) and saved queries (`saved_query`) from a SOURCE Superset metadata DB
into the TARGET one (this container's META_DB_URI). Neither has an export command, so rows are copied.

Merge semantics:
  * `query` rows are matched by client_id, `saved_query` rows by uuid; existing target rows are left alone.
  * Ids differ between labs, so user_id / created_by_fk / changed_by_fk are re-mapped BY USERNAME and
    database_id / db_id BY DATABASE NAME. Rows whose database does not exist in the target are skipped.
  * Original timestamps are kept. `results_key` is cleared: it points at the source's result cache,
    which the target does not have (the history entry and its SQL stay; cached result rows do not).

    docker exec superset_lab2 python /app/fake_data/sync_query_history.py
"""
import os
import sys
import uuid as uuid_mod

from sqlalchemy import MetaData, Table, create_engine, select


def _is_native_uuid(col):
    return "UUID" in str(col.type).upper()


def norm_uuid(v):
    """Canonical str(uuid), regardless of storage (BINARY(16) bytes on MySQL, native UUID on Postgres)."""
    if v is None:
        return None
    return str(uuid_mod.UUID(bytes=v)) if isinstance(v, bytes) else str(v)


def to_col_uuid(col, v):
    """Convert a uuid value into whatever this specific (reflected) column expects to store."""
    if v is None:
        return None
    u = uuid_mod.UUID(bytes=v) if isinstance(v, bytes) else (v if isinstance(v, uuid_mod.UUID) else uuid_mod.UUID(str(v)))
    return str(u) if _is_native_uuid(col) else u.bytes

SRC_META_URI = os.environ.get(
    "SRC_META_URI", "mysql+mysqldb://superset:superset@mysql_lab1:3306/superset_meta?charset=utf8mb4"
)
src, tgt = create_engine(SRC_META_URI), create_engine(os.environ["META_DB_URI"])
smd, tmd = MetaData(), MetaData()


def tables(*names):
    return {n: (Table(n, smd, autoload_with=src), Table(n, tmd, autoload_with=tgt)) for n in names}


T = tables("ab_user", "dbs", "query", "saved_query")


def id_map(sconn, tconn, table, key):
    s_t, t_t = T[table]
    by_key = {r[0]: r[1] for r in tconn.execute(select(t_t.c[key], t_t.c.id))}
    return {r[1]: by_key.get(r[0]) for r in sconn.execute(select(s_t.c[key], s_t.c.id))}


def copy_rows(sconn, tconn, table, dedupe_col, fk_maps, clear=()):
    s_t, t_t = T[table]
    is_uuid_dedupe = dedupe_col == "uuid"
    if is_uuid_dedupe:
        have = {norm_uuid(r[0]) for r in tconn.execute(select(t_t.c[dedupe_col]))}
    else:
        have = {r[0] for r in tconn.execute(select(t_t.c[dedupe_col]))}
    added = skipped = 0
    warns = []
    for row in sconn.execute(select(s_t).order_by(s_t.c.id)).mappings():
        key = norm_uuid(row[dedupe_col]) if is_uuid_dedupe else row[dedupe_col]
        if key in have:
            skipped += 1
            continue
        vals = {c.name: row[c.name] for c in t_t.columns if c.name in row and c.name != "id"}
        if "uuid" in vals:
            vals["uuid"] = to_col_uuid(t_t.c["uuid"], vals["uuid"])
        drop = False
        for col, (mapping, required) in fk_maps.items():
            if col in vals and vals[col] is not None:
                new = mapping.get(vals[col])
                if new is None and required:
                    warns.append(f"{table} {row[dedupe_col]!s:.12}: {col}={vals[col]} has no match in target, row skipped")
                    drop = True
                    break
                vals[col] = new
        if drop:
            continue
        for c in clear:
            if c in vals:
                vals[c] = None
        tconn.execute(t_t.insert().values(**vals))
        added += 1
    return added, skipped, warns


with src.connect() as sconn, tgt.begin() as tconn:
    users = id_map(sconn, tconn, "ab_user", "username")
    dbs = id_map(sconn, tconn, "dbs", "database_name")
    user_cols = {c: (users, False) for c in ("user_id", "created_by_fk", "changed_by_fk")}

    results = {
        "query": copy_rows(sconn, tconn, "query", "client_id",
                           {**user_cols, "database_id": (dbs, True)}, clear=("results_key",)),
        "saved_query": copy_rows(sconn, tconn, "saved_query", "uuid",
                                 {**user_cols, "db_id": (dbs, False)}),
    }

for name, (added, skipped, warns) in results.items():
    print(f"{name:<12} added {added}, skipped {skipped} (already in target)")
    for w in warns:
        print("  WARN", w)
