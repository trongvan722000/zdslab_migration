"""Give Lab 2 its OWN pre-existing metadata (users, connections, datasets, a dashboard),
so the merge from Lab 1 can be tested against a non-empty target.

    docker exec superset_lab2 python /app/fake_data/seed_lab2_existing.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import seed_fake_metadata as s  # noqa: E402  (reuses its helpers; META_DB_URI comes from the container env)

s.USERS = [
    ("lab2_nam", "Nam", "Nguyen", "Alpha"),
    ("lab2_linh", "Linh", "Tran", "Gamma"),
    ("lab2_hung", "Hung", "Le", "Admin"),
]
s.USER_PASSWORD = "Lab2Passw0rd!"

s.DATABASES = [
    ("Lab2 - Legacy Sales", "mysql+mysqldb://reader:reader_pwd@mysql_lab1:3306/sales"),
    ("Lab2 - Legacy Finance", "postgresql+psycopg2://reader:reader_pwd@postgres_lab1:5432/finance"),
]

s.DATASETS = {
    "legacy_orders": ("Lab2 - Legacy Sales", "sales", "orders", [
        ("order_id", "BIGINT", False), ("status", "VARCHAR(20)", False),
        ("amount", "DECIMAL(12, 2)", False), ("order_date", "DATETIME", True)]),
    "legacy_invoices": ("Lab2 - Legacy Finance", "public", "invoices", [
        ("invoice_id", "BIGINT", False), ("currency", "VARCHAR(3)", False),
        ("total", "NUMERIC(14, 2)", False), ("issued_at", "TIMESTAMP WITHOUT TIME ZONE", True)]),
}

s.DASHBOARDS = [
    ("Lab2 Legacy Dashboard", "lab2-legacy", [
        ("Lab2 orders by status", "pie", "legacy_orders", "status"),
        ("Lab2 invoices by currency", "pie", "legacy_invoices", "currency"),
    ]),
]

if __name__ == "__main__":
    s.main()
