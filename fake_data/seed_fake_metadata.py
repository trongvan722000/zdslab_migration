"""Seed metadata directly into a Superset metadata DB (MySQL or Postgres).

Run inside a Lab 1 Superset container (it already has SQLAlchemy, drivers, werkzeug, sqlalchemy_utils);
META_DB_URI / SUPERSET_SECRET_KEY are taken from the container env:
    docker exec superset_lab1_mysql python /app/fake_data/seed_fake_metadata.py
    docker exec superset_lab1_pg    python /app/fake_data/seed_fake_metadata.py

Idempotent: objects are looked up by name and skipped if they already exist.
"""
import json
import os
import random
import sys
import uuid
from datetime import datetime

from sqlalchemy import MetaData, String, Table, create_engine, func, select
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

META_DB_URI = os.environ["META_DB_URI"]
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY")
PASSWORD_MASK = "X" * 10

random.seed(42)
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


def encrypt(value):
    """Encrypt exactly like Superset does for dbs.password (sqlalchemy_utils EncryptedType + SECRET_KEY)."""
    if not SECRET_KEY:
        return None
    from sqlalchemy_utils import EncryptedType

    return EncryptedType(String(1024), SECRET_KEY).process_bind_param(value, engine.dialect)


# --------------------------------------------------------------------------- data
# Real data DBs created by initdb/*/10_lab1_data.sql. Hostnames are Lab 1's; the migration
# script rewrites them to Lab 2's after restore.
DATABASES = [
    ("MySQL - Sales", "mysql+mysqldb://reader:reader_pwd@mysql_lab1:3306/sales"),
    ("MySQL - CRM", "mysql+mysqldb://reader:reader_pwd@mysql_lab1:3306/crm"),
    ("Postgres - Finance", "postgresql+psycopg2://reader:reader_pwd@postgres_lab1:5432/finance"),
    ("Postgres - Warehouse", "postgresql+psycopg2://reader:reader_pwd@postgres_lab1:5432/warehouse"),
    ("Postgres - Marketing", "postgresql+psycopg2://reader:reader_pwd@postgres_lab1:5432/marketing"),
]

# key -> (database_name, schema, table_name, [(column, type, is_dttm)])
DATASETS = {
    "orders": ("MySQL - Sales", "sales", "orders", [
        ("order_id", "BIGINT", False), ("customer_id", "BIGINT", False),
        ("amount", "DECIMAL(12, 2)", False), ("status", "VARCHAR(20)", False),
        ("order_date", "DATETIME", True)]),
    "order_items": ("MySQL - Sales", "sales", "order_items", [
        ("item_id", "BIGINT", False), ("order_id", "BIGINT", False), ("sku", "VARCHAR(64)", False),
        ("qty", "INTEGER", False), ("price", "DECIMAL(12, 2)", False)]),
    "customers": ("MySQL - CRM", "crm", "customers", [
        ("customer_id", "BIGINT", False), ("full_name", "VARCHAR(255)", False),
        ("city", "VARCHAR(100)", False), ("segment", "VARCHAR(20)", False),
        ("created_at", "DATETIME", True)]),
    "tickets": ("MySQL - CRM", "crm", "tickets", [
        ("ticket_id", "BIGINT", False), ("customer_id", "BIGINT", False),
        ("status", "VARCHAR(20)", False), ("priority", "VARCHAR(10)", False),
        ("opened_at", "DATETIME", True)]),
    "invoices": ("Postgres - Finance", "public", "invoices", [
        ("invoice_id", "BIGINT", False), ("customer_id", "BIGINT", False),
        ("total", "NUMERIC(14, 2)", False), ("currency", "VARCHAR(3)", False),
        ("issued_at", "TIMESTAMP WITHOUT TIME ZONE", True)]),
    "payments": ("Postgres - Finance", "public", "payments", [
        ("payment_id", "BIGINT", False), ("invoice_id", "BIGINT", False),
        ("paid", "NUMERIC(14, 2)", False), ("method", "VARCHAR(20)", False),
        ("paid_at", "TIMESTAMP WITHOUT TIME ZONE", True)]),
    "fact_revenue": ("Postgres - Warehouse", "dw", "fact_revenue", [
        ("date_key", "DATE", True), ("region", "VARCHAR(50)", False),
        ("product_id", "BIGINT", False), ("revenue", "NUMERIC(18, 2)", False)]),
    "dim_product": ("Postgres - Warehouse", "dw", "dim_product", [
        ("product_id", "BIGINT", False), ("name", "VARCHAR(100)", False),
        ("category", "VARCHAR(100)", False), ("updated_at", "TIMESTAMP WITHOUT TIME ZONE", True)]),
    "campaigns": ("Postgres - Marketing", "public", "campaigns", [
        ("campaign_id", "BIGINT", False), ("name", "VARCHAR(100)", False),
        ("channel", "VARCHAR(50)", False), ("budget", "NUMERIC(12, 2)", False),
        ("start_date", "DATE", True)]),
    "ad_clicks": ("Postgres - Marketing", "public", "ad_clicks", [
        ("click_id", "BIGINT", False), ("campaign_id", "BIGINT", False),
        ("cost", "NUMERIC(10, 4)", False), ("clicked_at", "TIMESTAMP WITHOUT TIME ZONE", True)]),
}

# (username, first, last, role)
USERS = [
    ("zds_alice", "Alice", "Nguyen", "Alpha"),
    ("zds_bob", "Bob", "Tran", "Gamma"),
    ("zds_carol", "Carol", "Le", "Gamma"),
    ("zds_david", "David", "Pham", "sql_lab"),
    ("zds_emma", "Emma", "Hoang", "Gamma"),
    ("zds_frank", "Frank", "Vu", "Alpha"),
    ("zds_grace", "Grace", "Dang", "Gamma"),
    ("zds_henry", "Henry", "Bui", "Admin"),
]
USER_PASSWORD = "Passw0rd!"

# (dashboard_title, slug, [(chart_name, viz_type, dataset_key, groupby_column)])
DASHBOARDS = [
    ("Sales Overview", "sales-overview", [
        ("Orders per day", "echarts_timeseries_line", "orders", None),
        ("Orders by status", "pie", "orders", "status"),
        ("Items by SKU", "table", "order_items", "sku"),
        ("Customers by city", "pie", "customers", "city"),
        ("Tickets by priority", "table", "tickets", "priority"),
    ]),
    ("Finance KPIs", "finance-kpis", [
        ("Invoice count", "big_number_total", "invoices", None),
        ("Payments per day", "echarts_timeseries_bar", "payments", None),
        ("Revenue rows by region", "pie", "fact_revenue", "region"),
        ("Products by category", "table", "dim_product", "category"),
    ]),
    ("Marketing Funnel", "marketing-funnel", [
        ("Campaigns by channel", "pie", "campaigns", "channel"),
        ("Clicks per day", "echarts_timeseries_line", "ad_clicks", None),
    ]),
]


# --------------------------------------------------------------------------- seeders
def seed_users(conn):
    user_ids = {}
    for username, first, last, role in USERS:
        uid = find_id(conn, "ab_user", username=username)
        if uid is None:
            uid = insert(
                conn, "ab_user",
                first_name=first, last_name=last, username=username,
                email=f"{username}@zdslab.local",
                password=generate_password_hash(USER_PASSWORD),
                active=True, login_count=0, fail_login_count=0,
            )
            role_id = find_id(conn, "ab_role", name=role)
            if role_id:
                insert(conn, "ab_user_role", user_id=uid, role_id=role_id)
            print(f"  + user {username} (role={role})")
        user_ids[username] = uid
    return user_ids


def seed_databases(conn, admin_id):
    db_ids = {}
    for name, uri in DATABASES:
        dbid = find_id(conn, "dbs", database_name=name)
        if dbid is None:
            url = make_url(uri)
            masked = url.set(password=PASSWORD_MASK).render_as_string(hide_password=False)
            dbid = insert(
                conn, "dbs",
                database_name=name, sqlalchemy_uri=masked, password=encrypt(url.password),
                expose_in_sqllab=True, allow_run_async=False, allow_ctas=False,
                allow_cvas=False, allow_dml=False, allow_file_upload=False,
                allow_csv_upload=False, impersonate_user=False,
                configuration_method="sqlalchemy_form",
                extra=json.dumps({"metadata_params": {}, "engine_params": {},
                                  "metadata_cache_timeout": {}, "schemas_allowed_for_file_upload": []}),
                created_by_fk=admin_id, changed_by_fk=admin_id,
            )
            print(f"  + database {name}")
        db_ids[name] = dbid
    return db_ids


def seed_datasets(conn, db_ids, user_ids, admin_id):
    datasets = {}
    owners = list(user_ids.values())
    tables = T("tables")
    for key, (db_name, schema, table_name, columns) in DATASETS.items():
        dbid = db_ids[db_name]
        tid = find_id(conn, "tables", database_id=dbid, schema=schema, table_name=table_name)
        if tid is None:
            dttm = next((c for c, _, is_dttm in columns if is_dttm), None)
            tid = insert(
                conn, "tables",
                database_id=dbid, schema=schema, table_name=table_name,
                main_dttm_col=dttm, filter_select_enabled=True, is_sqllab_view=False, offset=0,
                schema_perm=f"[{db_name}].[{schema}]", extra="{}",
                created_by_fk=admin_id, changed_by_fk=admin_id,
            )
            conn.execute(tables.update().where(tables.c.id == tid)
                         .values(perm=f"[{db_name}].[{table_name}](id:{tid})"))
            for col, ctype, is_dttm in columns:
                insert(
                    conn, "table_columns",
                    table_id=tid, column_name=col, type=ctype, is_dttm=is_dttm,
                    groupby=True, filterable=True, is_active=True,
                    created_by_fk=admin_id, changed_by_fk=admin_id,
                )
            insert(
                conn, "sql_metrics",
                table_id=tid, metric_name="count", expression="COUNT(*)",
                metric_type="count", verbose_name="COUNT(*)",
                created_by_fk=admin_id, changed_by_fk=admin_id,
            )
            insert(conn, "sqlatable_user", table_id=tid, user_id=random.choice(owners))
            print(f"  + dataset {db_name} :: {schema}.{table_name}")
        dttm = next((c for c, _, d in columns if d), None)
        datasets[key] = {"id": tid, "db": db_name, "schema": schema, "table": table_name, "dttm": dttm}
    return datasets


def _chart_params(viz_type, ds, groupby):
    params = {
        "datasource": f"{ds['id']}__table",
        "viz_type": viz_type,
        "time_range": "No filter",
        "adhoc_filters": [],
        "row_limit": 1000,
    }
    if viz_type == "big_number_total":
        params["metric"] = "count"
    elif viz_type == "pie":
        params.update(metric="count", groupby=[groupby], show_labels=True, show_legend=True)
    elif viz_type == "table":
        params.update(query_mode="aggregate", metrics=["count"], groupby=[groupby])
    elif viz_type.startswith("echarts_timeseries"):
        params.update(metrics=["count"], x_axis=ds["dttm"], time_grain_sqla="P1D", groupby=[])
    return params


def _position_json(chart_refs):
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
    }
    for i in range(0, len(chart_refs), 3):
        row_id = f"ROW-{i // 3}"
        pos["GRID_ID"]["children"].append(row_id)
        pos[row_id] = {
            "type": "ROW", "id": row_id, "children": [],
            "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for chart_id, chart_uuid, name in chart_refs[i:i + 3]:
            key = f"CHART-{chart_id}"
            pos[row_id]["children"].append(key)
            pos[key] = {
                "type": "CHART", "id": key, "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {"chartId": chart_id, "uuid": str(chart_uuid), "sliceName": name,
                         "width": 4, "height": 50},
            }
    return pos


def seed_dashboards_and_charts(conn, datasets, user_ids, admin_id):
    owners = list(user_ids.values())
    for title, slug, charts in DASHBOARDS:
        if find_id(conn, "dashboards", slug=slug) is not None:
            continue
        chart_refs = []
        for name, viz_type, ds_key, groupby in charts:
            ds = datasets[ds_key]
            chart_uuid = uuid.uuid4()
            sid = insert(
                conn, "slices",
                slice_name=name, viz_type=viz_type, datasource_type="table",
                datasource_id=ds["id"], datasource_name=f"{ds['schema']}.{ds['table']}",
                params=json.dumps(_chart_params(viz_type, ds, groupby)), uuid=chart_uuid,
                perm=f"[{ds['db']}].[{ds['table']}](id:{ds['id']})",
                schema_perm=f"[{ds['db']}].[{ds['schema']}]",
                created_by_fk=admin_id, changed_by_fk=admin_id,
            )
            insert(conn, "slice_user", slice_id=sid, user_id=random.choice(owners))
            chart_refs.append((sid, chart_uuid, name))
            print(f"  + chart {name}")

        dash_id = insert(
            conn, "dashboards",
            dashboard_title=title, slug=slug, published=True,
            position_json=json.dumps(_position_json(chart_refs)),
            json_metadata=json.dumps({
                "color_scheme": "supersetColors", "refresh_frequency": 0,
                "expanded_slices": {}, "label_colors": {}, "timed_refresh_immune_slices": [],
                "cross_filters_enabled": True, "native_filter_configuration": [],
            }),
            css="", created_by_fk=admin_id, changed_by_fk=admin_id,
        )
        for sid, _, _ in chart_refs:
            insert(conn, "dashboard_slices", dashboard_id=dash_id, slice_id=sid)
        insert(conn, "dashboard_user", dashboard_id=dash_id, user_id=random.choice(owners))
        print(f"  + dashboard {title}")


def summary(conn):
    print(f"\nRow counts in {make_url(META_DB_URI).render_as_string(hide_password=True)}:")
    for name in ("ab_user", "dbs", "tables", "table_columns", "sql_metrics", "slices", "dashboards"):
        print(f"  {name:<14} {conn.execute(select(func.count()).select_from(T(name))).scalar()}")


def main():
    if not SECRET_KEY:
        print("WARN: SUPERSET_SECRET_KEY not set -> dbs.password left NULL", file=sys.stderr)
    with engine.begin() as conn:
        admin_id = find_id(conn, "ab_user", username="admin")
        if admin_id is None:
            sys.exit("admin user not found - wait for the Superset container to finish bootstrapping")
        print("Seeding users...")
        user_ids = seed_users(conn)
        print("Seeding database connections...")
        db_ids = seed_databases(conn, admin_id)
        print("Seeding datasets...")
        datasets = seed_datasets(conn, db_ids, user_ids, admin_id)
        print("Seeding charts & dashboards...")
        seed_dashboards_and_charts(conn, datasets, user_ids, admin_id)
        summary(conn)


if __name__ == "__main__":
    main()
