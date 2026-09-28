"""Import a Superset export ZIP (dashboards or datasources) into the running instance via REST API.

Why not `superset import-dashboards`? The CLI cannot supply database passwords, and exported ZIPs never
contain them, so the import is rejected. The REST endpoints accept a `passwords` map.

    python import_bundle.py dashboard  /tmp/dashboards.zip  [admin_user admin_password]
    python import_bundle.py dataset    /tmp/datasources.zip

Passwords, looked up per connection by database name, first match wins:
  1. JSON file at path in env DB_PASSWORDS_FILE   ({"MySQL - Sales": "pwd1", ...})  <- use this for many connections
  2. JSON map in env DB_PASSWORDS_JSON            (same shape)
  3. env DB_PASSWORD, used for every connection not listed above (default: reader_pwd)
Login: args [admin_user admin_password] (default admin/admin), URL from env SUPERSET_URL (default http://localhost:8088),
env AUTH_PROVIDER = db (default) or ldap.
Objects that already exist (same UUID) are overwritten; everything else in the target is left alone.
"""
import json
import os
import re
import sys
import zipfile

import requests
import yaml

kind, zip_path = sys.argv[1], sys.argv[2]
user = sys.argv[3] if len(sys.argv) > 3 else "admin"
password = sys.argv[4] if len(sys.argv) > 4 else "admin"
base = os.environ.get("SUPERSET_URL", "http://localhost:8088")
provider = os.environ.get("AUTH_PROVIDER", "db")  # "db" for local accounts, "ldap" when Superset logs in via LDAP
default_pwd = os.environ.get("DB_PASSWORD", "reader_pwd")
per_db = json.loads(os.environ.get("DB_PASSWORDS_JSON", "{}"))
if os.environ.get("DB_PASSWORDS_FILE"):
    with open(os.environ["DB_PASSWORDS_FILE"]) as f:
        per_db.update(json.load(f))

passwords = {}
with zipfile.ZipFile(zip_path) as z:
    for name in z.namelist():
        m = re.match(r"^[^/]+/(databases/[^/]+\.yaml)$", name)
        if m:
            db_name = yaml.safe_load(z.read(name))["database_name"]
            passwords[m.group(1)] = per_db.get(db_name, default_pwd)
            if db_name not in per_db:
                print(f"  note: no specific password for '{db_name}', using DB_PASSWORD default")

s = requests.Session()
r = s.post(f"{base}/api/v1/security/login",
           json={"username": user, "password": password, "provider": provider, "refresh": False})
r.raise_for_status()
s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
s.headers["X-CSRFToken"] = s.get(f"{base}/api/v1/security/csrf_token/").json()["result"]
s.headers["Referer"] = base

with open(zip_path, "rb") as f:
    r = s.post(
        f"{base}/api/v1/{kind}/import/",
        files={"formData": (os.path.basename(zip_path), f, "application/zip")},
        data={"overwrite": "true", "passwords": json.dumps(passwords)},
    )
print(f"{kind} import: HTTP {r.status_code} {r.text[:400]}")
sys.exit(0 if r.status_code == 200 else 1)
