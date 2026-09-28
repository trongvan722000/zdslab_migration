"""Print old (source) -> new (target) ids of dashboards and charts, matched by uuid, as CSV on stdout.

After the merge every imported dashboard/chart gets a NEW numeric id in the target, so bookmarks and links that
contain the old id (/superset/dashboard/<id>/) break; links that use the dashboard slug keep working.
Use this to build redirects or to tell users which links changed.

    docker exec -e SRC_META_URI=... superset_lab2 python /tmp/migration_tools/id_mapping.py > id_mapping.csv
(needs META_DB_URI = target metadata DB and SRC_META_URI = source metadata DB, both read-only is enough)
"""
import csv
import os
import sys

from sqlalchemy import create_engine, text

src = create_engine(os.environ["SRC_META_URI"])
tgt = create_engine(os.environ["META_DB_URI"])
QUERIES = {
    "dashboard": "SELECT HEX(uuid), id, COALESCE(slug, ''), dashboard_title FROM dashboards",
    "chart": "SELECT HEX(uuid), id, '', slice_name FROM slices",
}
w = csv.writer(sys.stdout)
w.writerow(["type", "old_id", "new_id", "slug", "title"])
with src.connect() as s, tgt.connect() as t:
    for kind, sql in QUERIES.items():
        new = {r[0]: r[1] for r in t.execute(text(sql))}
        for u, old_id, slug, title in s.execute(text(sql)):
            w.writerow([kind, old_id, new.get(u, "NOT_MIGRATED"), slug, title])
