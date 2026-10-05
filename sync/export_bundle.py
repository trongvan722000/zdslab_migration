"""Export ALL datasets or ALL dashboards of THIS Superset to a ZIP, as a chosen user (replaces the CLI on real data).

Why this exists: in 2.1.x `superset export-datasources` / `export-dashboards` hard-code `find_user(username="admin")`
and have no --username option. A real metadata DB has no user called `admin`, so g.user is None and the export dies
with `AttributeError: 'NoneType' object has no attribute 'is_anonymous'`. Creating an `admin` user would write into
the source metadata; this runs the same Export*Command the CLI uses, read-only, as any existing user.

    docker exec superset_lab1 python /app/sync/export_bundle.py dataset   /tmp/datasources.zip <username> 2>&1 | grep -E "^export|Error"
    docker exec superset_lab1 python /app/sync/export_bundle.py dashboard /tmp/dashboards.zip  <username> 2>&1 | grep -E "^export|Error"
    docker cp superset_lab1:/tmp/datasources.zip backup/datasources.zip

username: an existing, active user with the Admin role (default: admin), only used to pass Superset's access filter.
Find one with:  SELECT u.username FROM ab_user u JOIN ab_user_role ur ON ur.user_id = u.id
                JOIN ab_role r ON r.id = ur.role_id WHERE r.name = 'Admin' AND u.active = 1;
The ZIP has the same layout as the CLI's, so import_bundle_direct.py loads it unchanged.
"""
import sys
from datetime import datetime
from zipfile import ZipFile

from superset.app import create_app

if len(sys.argv) < 3 or sys.argv[1] not in ("dataset", "dashboard"):
    sys.exit("usage: export_bundle.py dataset|dashboard <out.zip> [username]")
kind, out = sys.argv[1], sys.argv[2]
username = sys.argv[3] if len(sys.argv) > 3 else "admin"

app = create_app()
with app.app_context():
    from flask import g

    from superset import db, security_manager

    if kind == "dataset":
        from superset.connectors.sqla.models import SqlaTable as Model

        try:  # 2.1.x
            from superset.datasets.commands.export import ExportDatasetsCommand as Command
        except ImportError:  # 3.x and later
            from superset.commands.dataset.export import ExportDatasetsCommand as Command
    else:
        from superset.models.dashboard import Dashboard as Model

        try:  # 2.1.x
            from superset.dashboards.commands.export import ExportDashboardsCommand as Command
        except ImportError:  # 3.x and later
            from superset.commands.dashboard.export import ExportDashboardsCommand as Command

    g.user = security_manager.find_user(username=username)
    if g.user is None:
        sys.exit(f"user '{username}' does not exist in this Superset")

    ids = [id_ for (id_,) in db.session.query(Model.id).all()]
    root = f"{kind}_export_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    counts = {}
    with ZipFile(out, "w") as bundle:
        for file_name, content in Command(ids).run():
            if callable(content):  # newer versions yield a callable instead of the text
                content = content()
            with bundle.open(f"{root}/{file_name}", "w") as fp:
                fp.write(content.encode())
            top = file_name.split("/")[0]
            counts[top] = counts.get(top, 0) + 1

# stdout also carries Superset's own log lines: grep for the lines below (they all start with "export").
for top in sorted(counts):
    print(f"export:   {top:<12} {counts[top]} file(s)")
n = counts.get(f"{kind}s", 0)
print(f"export: wrote {out}: {n} of {len(ids)} {kind}(s)")
if n != len(ids):
    sys.exit(f"export: ERROR {kind} count mismatch: check that '{username}' has the Admin role")
