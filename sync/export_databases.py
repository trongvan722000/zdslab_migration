"""Export EVERY database connection of THIS Superset to a ZIP that import_bundle_direct.py can load as `database`.

Why this exists: `superset export-datasources` exports datasets and only the connections those datasets use.
A connection with no dataset (used only from SQL Lab, or not used yet) is NOT in datasources.zip, so it never
reaches Lab 2 (seen on real data: 43 connections in Lab 1, only 20 in the bundle). There is no CLI command to export
connections; this runs Superset's own ExportDatabasesCommand in-process, the same one the UI "Export" button uses.

    docker exec superset_lab1 python /app/sync/export_databases.py /tmp/databases.zip [username] 2>&1 | grep -E "^export|Error"
    docker cp superset_lab1:/tmp/databases.zip backup/databases.zip
    unzip -l backup/databases.zip | grep -c "/databases/"      # must equal the number of connections in Lab 1

username: an existing user who can see all connections (default: admin), only used to pass Superset's access filter.
Datasets are left out on purpose (datasources.zip carries them). Passwords are never in the ZIP (Superset masks
them); import_bundle_direct.py adds them from DB_PASSWORDS_FILE.
"""
import sys
from datetime import datetime
from zipfile import ZipFile

from superset.app import create_app

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/databases.zip"
username = sys.argv[2] if len(sys.argv) > 2 else "admin"

app = create_app()
with app.app_context():
    from flask import g

    from sqlalchemy import func

    from superset import db, security_manager
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    try:  # 2.1.x
        from superset.databases.commands.export import ExportDatabasesCommand
    except ImportError:  # 3.x and later
        from superset.commands.database.export import ExportDatabasesCommand

    g.user = security_manager.find_user(username=username)
    if g.user is None:
        sys.exit(f"user '{username}' does not exist in this Superset")

    dbs = db.session.query(Database.id, Database.database_name).order_by(Database.id).all()
    ids = [id_ for id_, _ in dbs]
    n_datasets = dict(db.session.query(SqlaTable.database_id, func.count(SqlaTable.id)).group_by(SqlaTable.database_id))
    with_ds = [(name, n_datasets[id_]) for id_, name in dbs if n_datasets.get(id_)]
    without_ds = [name for id_, name in dbs if not n_datasets.get(id_)]
    root = f"database_export_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    n = 0
    with ZipFile(out, "w") as bundle:
        for file_name, content in ExportDatabasesCommand(ids, export_related=False).run():
            if callable(content):  # newer versions yield a callable instead of the text
                content = content()
            with bundle.open(f"{root}/{file_name}", "w") as fp:
                fp.write(content.encode())
            n += file_name.startswith("databases/")

# stdout also carries Superset's own log lines: grep for the lines below (they all start with "export").
print(f"export: {len(with_ds)} connection(s) WITH datasets (also in datasources.zip):")
for name, k in with_ds:
    print(f"export:   [{k:>4} dataset(s)] {name}")
print(f"export: {len(without_ds)} connection(s) WITHOUT datasets (only in this ZIP):")
for name in without_ds:
    print(f"export:   [   0 dataset(s)] {name}")
print(f"export: wrote {out}: {n} of {len(ids)} connection(s)")
if n != len(ids):
    sys.exit("export: ERROR connection count mismatch: check that the user can access all databases")
