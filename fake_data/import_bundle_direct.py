"""Import a Superset export ZIP by calling Superset's own import command INSIDE the app, with no web/API call.

Why this exists: the REST import (import_bundle.py) needs a login. When login is LDAP + OTP, or when a proxy/gunicorn
timeout could cut a big import, that is painful. Running the same command in-process needs no login, no token and
has no HTTP timeout. (The plain CLI `superset import-dashboards` cannot be used: it has no way to pass the database
passwords that exports never contain. This script passes them.)

    python import_bundle_direct.py dataset   /tmp/datasources.zip  [owner_username]
    python import_bundle_direct.py dashboard /tmp/dashboards.zip   [owner_username]

owner_username: existing Superset user recorded as owner of the imported objects (default: admin). No password needed.

Passwords per connection, looked up by database name (first match wins):
  1. JSON file at env DB_PASSWORDS_FILE        {"MySQL - Sales": "pwd", ...}
  2. JSON in env DB_PASSWORDS_JSON             (same shape)
  3. env DB_PASSWORD                           default for connections not listed (default: reader_pwd)
Existing objects with the same UUID are overwritten; everything else in the target is left alone.
Run it in the TARGET Superset (needs that instance's config / SECRET_KEY, which encrypts the stored passwords).
"""
import json
import os
import sys
import zipfile

import yaml

kind, zip_path = sys.argv[1], sys.argv[2]
owner = sys.argv[3] if len(sys.argv) > 3 else "admin"
default_pwd = os.environ.get("DB_PASSWORD", "reader_pwd")
per_db = json.loads(os.environ.get("DB_PASSWORDS_JSON", "{}"))
if os.environ.get("DB_PASSWORDS_FILE"):
    with open(os.environ["DB_PASSWORDS_FILE"]) as f:
        per_db.update(json.load(f))

from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from flask import g

    from superset import security_manager
    from superset.commands.exceptions import CommandInvalidError
    from superset.commands.importers.v1.utils import get_contents_from_bundle

    if kind == "dataset":
        from superset.commands.dataset.importers.dispatcher import ImportDatasetsCommand as Command
    elif kind == "dashboard":
        from superset.commands.dashboard.importers.dispatcher import ImportDashboardsCommand as Command
    else:
        sys.exit("kind must be 'dataset' or 'dashboard'")

    g.user = security_manager.find_user(username=owner)
    if g.user is None:
        sys.exit(f"owner user '{owner}' does not exist in this Superset")

    with zipfile.ZipFile(zip_path) as z:
        contents = get_contents_from_bundle(z)

    passwords = {}
    for name, body in contents.items():
        if name.startswith("databases/"):
            db_name = yaml.safe_load(body)["database_name"]
            passwords[name] = per_db.get(db_name, default_pwd)
            if db_name not in per_db:
                print(f"  note: no specific password for '{db_name}', using DB_PASSWORD default")

    try:
        Command(contents, passwords=passwords, overwrite=True).run()
        print(f"{kind} import (direct): OK, {len(passwords)} connection(s) in bundle, owner={owner}")
    except CommandInvalidError as e:
        print(f"{kind} import (direct): REJECTED by validation")
        print(json.dumps(e.normalized_messages(), indent=1, default=str)[:2500])
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        # Superset wraps the real cause (wrong password, host unreachable...) inside a generic import error.
        chain, cur = [], e
        while cur is not None and len(chain) < 6:
            line = f"{type(cur).__name__}: {str(cur).splitlines()[0][:220] if str(cur) else ''}"
            if not chain or chain[-1] != line:
                chain.append(line)
            cur = cur.__cause__ or cur.__context__
        print(f"{kind} import (direct): FAILED, nothing was imported")
        print("  cause chain (last line is the root cause):")
        for c in chain:
            print("   -", c)
        sys.exit(1)
