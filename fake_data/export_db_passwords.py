"""Write {connection name: password} for every database connection of THIS Superset to a JSON file.

Connection passwords are stored encrypted with SECRET_KEY; Superset's own model decrypts them, so nobody has to
type or look up 43 passwords by hand. The output is PLAINTEXT secrets: keep it out of git, chmod 600, delete it
after the import.

    docker exec superset_lab1 python /app/fake_data/export_db_passwords.py /tmp/passwords.json
    docker cp superset_lab1:/tmp/passwords.json backup/passwords.json && chmod 600 backup/passwords.json
    docker exec superset_lab1 rm /tmp/passwords.json

(A file, not stdout: Superset prints its own log lines on stdout and they would corrupt the JSON.)
"""
import json
import os
import sys

from superset.app import create_app

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database

    result, no_password = {}, []
    for d in db.session.query(Database).order_by(Database.id):
        if d.password:
            result[d.database_name] = d.password
        else:
            no_password.append(d.database_name)

out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/passwords.json"
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print(f"wrote {out}: {len(result)} passwords exported; {len(no_password)} connection(s) without a stored password: {no_password}")
