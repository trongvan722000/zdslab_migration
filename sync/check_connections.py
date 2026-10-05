"""List every Superset DB connection and try to connect (decrypts dbs.password with SECRET_KEY).

    docker exec superset_lab2 python /app/sync/check_connections.py
"""
import sys

from superset.app import create_app

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database

    failed = 0
    for d in db.session.query(Database).order_by(Database.id):
        try:
            with d.get_sqla_engine() as eng:
                eng.connect().close()
            status = "connect OK"
        except Exception as e:
            failed += 1
            status = f"FAIL {type(e).__name__}: {str(e)[:100]}"
        print(f"   {d.database_name:<22} {d.sqlalchemy_uri:<66} {status}")
    sys.exit(1 if failed else 0)
