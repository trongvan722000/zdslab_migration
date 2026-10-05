"""Helpers for writing rows into the TARGET Superset metadata DB (the container's own META_DB_URI).

Works on MySQL/MariaDB and Postgres: fills NOT NULL columns that differ across Superset versions,
converts uuid to the right storage type, and draws ids from FAB's unattached Postgres sequences.
Same helpers as fake_data/seed_fake_metadata.py, kept here so sync/ has no dependency on fake_data/.
"""
import os
import uuid
from datetime import datetime

from sqlalchemy import MetaData, Table, create_engine, select

META_DB_URI = os.environ["META_DB_URI"]
engine = create_engine(META_DB_URI)
IS_PG = engine.dialect.name == "postgresql"
md = MetaData()
_tables = {}


def T(name):
    if name not in _tables:
        _tables[name] = Table(name, md, autoload_with=engine)
    return _tables[name]


def _is_native_uuid(col):
    return "UUID" in str(col.type).upper()


def _fill_required(table, row):
    """Give a value to NOT NULL columns without a DB default (schema differs across versions)."""
    now = datetime.utcnow()
    for col in table.columns:
        if col.name in row or col.nullable or col.server_default is not None or col.primary_key:
            continue
        try:
            pytype = col.type.python_type
        except NotImplementedError:
            pytype = str
        if col.name == "uuid" or _is_native_uuid(col):
            row[col.name] = uuid.uuid4()
        elif pytype is bool:
            row[col.name] = False
        elif pytype in (int, float):
            row[col.name] = 0
        elif pytype is datetime:
            row[col.name] = now
        else:
            row[col.name] = "{}" if "json" in col.name else ""
    return row


def insert(conn, _table, **values):
    table = T(_table)
    values = {k: v for k, v in values.items() if k in table.c}
    now = datetime.utcnow()
    for audit in ("created_on", "changed_on"):
        if audit in table.c:
            values.setdefault(audit, now)
    if "uuid" in table.c:
        values.setdefault("uuid", uuid.uuid4())
    _fill_required(table, values)

    # Superset stores uuid as native UUID on Postgres but BINARY(16) on MySQL.
    for k, v in values.items():
        if isinstance(v, uuid.UUID):
            values[k] = str(v) if _is_native_uuid(table.c[k]) else v.bytes

    pk = list(table.primary_key.columns)
    if IS_PG and len(pk) == 1 and pk[0].name not in values and pk[0].server_default is None:
        # FAB association tables use a sequence that is not attached as a column default.
        seq = conn.exec_driver_sql(
            f"SELECT pg_get_serial_sequence('{_table}', '{pk[0].name}')"
        ).scalar() or f"{_table}_{pk[0].name}_seq"
        values[pk[0].name] = conn.exec_driver_sql(f"SELECT nextval('{seq}')").scalar()

    result = conn.execute(table.insert().values(**values))
    return result.inserted_primary_key[0] if result.inserted_primary_key else None


def find_id(conn, _table, **where):
    table = T(_table)
    stmt = select(table.c.id)
    for k, v in where.items():
        stmt = stmt.where(table.c[k] == v)
    return conn.execute(stmt).scalar()
