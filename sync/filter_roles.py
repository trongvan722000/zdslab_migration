"""Keep only CUSTOM roles from a `superset fab export-roles` file, ready for `superset fab import-roles`.

Importing the full file would also merge the source's old permissions into the target's BUILT-IN roles
(Admin/Alpha/Gamma/... grow with permissions the newer Superset renamed or dropped). Permissions on a
specific object carry the source's id ("[db].[table](id:N)") and would point at the wrong object in the
target, so they are dropped too and must be re-granted after the import (see README, Bước 2b).

    docker exec superset_lab1 superset fab export-roles --path /tmp/roles.json
    docker cp superset_lab1:/tmp/roles.json - | docker cp - superset_lab2:/tmp/
    docker exec -u root superset_lab2 chown superset /tmp/roles.json
    docker exec superset_lab2 python /app/sync/filter_roles.py /tmp/roles.json /tmp/roles_custom.json
    docker exec superset_lab2 superset fab import-roles --path /tmp/roles_custom.json
"""
import json
import sys

BUILTIN = {"Admin", "Alpha", "Gamma", "Public", "sql_lab", "granter"}

src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/roles.json"
out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/roles_custom.json"

custom, dropped = [], {}
for role in json.load(open(src)):
    if role["name"] in BUILTIN:
        continue
    keep = [p for p in role["permissions"] if "(id:" not in p["view_menu"]["name"]]
    if len(keep) != len(role["permissions"]):
        dropped[role["name"]] = len(role["permissions"]) - len(keep)
    custom.append({**role, "permissions": keep})

json.dump(custom, open(out, "w"), indent=1)
print(f"wrote {out}: {len(custom)} custom role(s), {sum(dropped.values())} id-bound permission(s) dropped")
for name, n in sorted(dropped.items()):
    print(f"  {name}: {n} permission(s) to re-grant after the import")
