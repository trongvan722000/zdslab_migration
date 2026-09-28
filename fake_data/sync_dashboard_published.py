"""Copy the `published` flag of dashboards from the SOURCE Superset metadata DB to the TARGET (matched by uuid).

Why: exports from Superset 2.1.x do not contain `published`, so every dashboard imported into a newer
Superset comes out UNPUBLISHED, and users who are not owners/admins (Alpha, Gamma...) stop seeing it.
Only dashboards that exist in the target are touched; nothing is created or deleted.

    docker exec superset_lab2 python /app/fake_data/sync_dashboard_published.py
"""
import os

from sqlalchemy import MetaData, Table, create_engine, select

SRC_META_URI = os.environ.get(
    "SRC_META_URI", "mysql+mysqldb://superset:superset@mysql_lab1:3306/superset_meta?charset=utf8mb4"
)
src, tgt = create_engine(SRC_META_URI), create_engine(os.environ["META_DB_URI"])
S = Table("dashboards", MetaData(), autoload_with=src)
T = Table("dashboards", MetaData(), autoload_with=tgt)

with src.connect() as sconn, tgt.begin() as tconn:
    published = {r.uuid: r.published for r in sconn.execute(select(S.c.uuid, S.c.published))}
    changed = same = 0
    for row in tconn.execute(select(T.c.id, T.c.dashboard_title, T.c.uuid, T.c.published)).all():
        if row.uuid not in published:
            continue  # a Lab 2 dashboard that does not come from Lab 1
        want = bool(published[row.uuid])
        if bool(row.published) == want:
            same += 1
            continue
        tconn.execute(T.update().where(T.c.id == row.id).values(published=want))
        changed += 1
        print(f"  {row.dashboard_title}: published {bool(row.published)} -> {want}")
print(f"dashboards: {changed} updated, {same} already correct")
