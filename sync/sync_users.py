"""Add users from a SOURCE Superset metadata DB to the TARGET one (the container's own META_DB_URI).

Merge semantics: matched by `username`. Users that already exist in the target are left untouched;
missing ones are inserted with the same password hash and roles matched BY ROLE NAME (never by id).

    docker exec superset_lab2 python /app/sync/sync_users.py
    SRC_META_URI=... docker exec -e SRC_META_URI=... superset_lab2 python /app/sync/sync_users.py
"""
import os
import sys

from sqlalchemy import MetaData, Table, create_engine, select

sys.path.insert(0, os.path.dirname(__file__))
import meta_db as target  # noqa: E402  (its engine points at this container's META_DB_URI)

SRC_META_URI = os.environ.get(
    "SRC_META_URI", "mysql+mysqldb://superset:superset@mysql_lab1:3306/superset_meta?charset=utf8mb4"
)
COPY_COLUMNS = ("first_name", "last_name", "username", "password", "active", "email")

src = create_engine(SRC_META_URI)

src_md = MetaData()
S_USER, S_ROLE, S_UR = (Table(n, src_md, autoload_with=src) for n in ("ab_user", "ab_role", "ab_user_role"))

added, skipped, warned = [], [], []
with src.connect() as sconn, target.engine.begin() as tconn:
    roles_of = {}
    for uid, rname in sconn.execute(
        select(S_UR.c.user_id, S_ROLE.c.name).join(S_ROLE, S_ROLE.c.id == S_UR.c.role_id)
    ):
        roles_of.setdefault(uid, []).append(rname)

    for row in sconn.execute(select(S_USER).order_by(S_USER.c.id)).mappings():
        username = row["username"]
        if target.find_id(tconn, "ab_user", username=username) is not None:
            skipped.append(username)
            continue
        # Guard on a real email: find_id(email=None) becomes "email IS NULL" and would match an unrelated user.
        if row["email"] and target.find_id(tconn, "ab_user", email=row["email"]) is not None:
            warned.append(f"{username}: email {row['email']} already used by another target user, skipped")
            continue
        new_id = target.insert(
            tconn, "ab_user",
            **{c: row[c] for c in COPY_COLUMNS}, login_count=0, fail_login_count=0,
        )
        for rname in roles_of.get(row["id"], []):
            role_id = target.find_id(tconn, "ab_role", name=rname)
            if role_id is None:
                warned.append(f"{username}: role '{rname}' does not exist in target (use fab export-roles / import-roles)")
                continue
            target.insert(tconn, "ab_user_role", user_id=new_id, role_id=role_id)
        added.append(f"{username} ({', '.join(roles_of.get(row['id'], [])) or 'no role'})")

print(f"added   {len(added)}: " + ", ".join(added))
print(f"skipped {len(skipped)} (already in target): " + ", ".join(skipped))
for w in warned:
    print("WARN", w)
