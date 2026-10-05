"""Copy the OWNERS of datasets, charts and dashboards from the SOURCE Superset metadata DB to the TARGET one.

Why: export ZIPs carry no owners, so every imported object is owned by the user who ran the import. Owners matter:
an Alpha user can only edit objects they own, and being owner of a dataset is by itself enough to query it
(security_manager.raise_for_access: `or self.is_owner(datasource)`, in 2.1.1 and 5.0.0). A user whose only access
to a dataset was ownership loses it after the import.

Merge semantics:
  * Objects are matched by uuid (kept by export/import), users by username. Ids differ between labs and are never copied.
  * Owner rows are only ADDED (sqlatable_user, slice_user, dashboard_user); existing ones are left alone, so re-running
    is safe. Objects that exist only in the target (no uuid in the source) are not touched.
  * --remove-owner USERNAME: also drop USERNAME (the account that ran import_bundle_direct.py) from the owners of
    objects that come from the source, unless USERNAME was an owner there too. It is kept on objects for which no
    source owner could be mapped, so no object is left without an owner by this script.
  * --dry-run: do everything inside a transaction and roll it back (prints what would change).

Run AFTER import_bundle_direct.py (objects must exist) and sync_users.py (owners must exist):

    docker exec superset_lab2 python /app/sync/sync_owners.py --dry-run
    docker exec superset_lab2 python /app/sync/sync_owners.py --remove-owner <import_user>
"""
import argparse
import os
import sys
import uuid as uuid_mod

from sqlalchemy import MetaData, Table, create_engine, select

sys.path.insert(0, os.path.dirname(__file__))
import meta_db as target  # noqa: E402  (its engine points at this container's META_DB_URI)

SRC_META_URI = os.environ.get(
    "SRC_META_URI", "mysql+mysqldb://superset:superset@mysql_lab1:3306/superset_meta?charset=utf8mb4"
)
# (object table, owner association table, column of the association table pointing at the object)
OWNED = (
    ("tables", "sqlatable_user", "table_id"),
    ("slices", "slice_user", "slice_id"),
    ("dashboards", "dashboard_user", "dashboard_id"),
)

ap = argparse.ArgumentParser()
ap.add_argument("--remove-owner", metavar="USERNAME", help="drop this user (the importer) from migrated objects")
ap.add_argument("--dry-run", action="store_true", help="roll back at the end")
args = ap.parse_args()

src = create_engine(SRC_META_URI)
src_md = MetaData()


def S(name):
    return Table(name, src_md, autoload_with=src)


def norm_uuid(v):
    """Canonical str(uuid), regardless of storage (BINARY(16) bytes on MySQL, native UUID on Postgres)."""
    if v is None:
        return None
    return str(uuid_mod.UUID(bytes=v)) if isinstance(v, bytes) else str(v)


S_USER = S("ab_user")
with src.connect() as sconn, target.engine.connect() as tconn:
    trans = tconn.begin()
    T_USER = target.T("ab_user")
    user_id = {r.username: r.id for r in tconn.execute(select(T_USER.c.username, T_USER.c.id))}
    remove_id = None
    if args.remove_owner:
        remove_id = user_id.get(args.remove_owner)
        if remove_id is None:
            sys.exit(f"--remove-owner: user '{args.remove_owner}' does not exist in target")

    missing_users = set()
    for obj, assoc, fk in OWNED:
        s_obj, s_as = S(obj), S(assoc)
        t_obj, t_as = target.T(obj), target.T(assoc)

        src_owners = {}  # uuid -> {username, ...} in the source
        for u, name in sconn.execute(
            select(s_obj.c.uuid, S_USER.c.username).select_from(
                s_as.join(s_obj, s_obj.c.id == s_as.c[fk]).join(S_USER, S_USER.c.id == s_as.c.user_id)
            )
        ):
            if u is not None:
                src_owners.setdefault(norm_uuid(u), set()).add(name)

        obj_id = {norm_uuid(u): id_ for u, id_ in tconn.execute(select(t_obj.c.uuid, t_obj.c.id)) if u is not None}
        have = {(o, u) for o, u in tconn.execute(select(t_as.c[fk], t_as.c.user_id))}

        added = removed = not_imported = 0
        for key, names in src_owners.items():
            oid = obj_id.get(key)
            if oid is None:
                not_imported += 1
                continue
            mapped = 0
            for name in sorted(names):
                uid = user_id.get(name)
                if uid is None:
                    missing_users.add(name)
                    continue
                mapped += 1
                if (oid, uid) not in have:
                    target.insert(tconn, assoc, **{fk: oid, "user_id": uid})
                    have.add((oid, uid))
                    added += 1
            if remove_id is not None and mapped and args.remove_owner not in names and (oid, remove_id) in have:
                tconn.execute(t_as.delete().where(t_as.c[fk] == oid, t_as.c.user_id == remove_id))
                have.discard((oid, remove_id))
                removed += 1

        line = f"{obj:<11} {len(src_owners)} owned in source: {added} owner row(s) added"
        if remove_id is not None:
            line += f", '{args.remove_owner}' removed from {removed}"
        print(line)
        if not_imported:
            print(f"  WARN {not_imported} {obj} owned in source are not in target (not imported yet?), skipped")

    for name in sorted(missing_users):
        print(f"WARN owner '{name}' does not exist in target (run sync_users.py first), not added")

    if args.dry_run:
        trans.rollback()
        print("DRY RUN: rolled back, nothing written")
    else:
        trans.commit()
