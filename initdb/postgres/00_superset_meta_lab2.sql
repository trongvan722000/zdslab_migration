-- Runs on postgres_lab2: the Superset metadata DB + its owner (Lab 2's real environment uses Postgres, not MySQL).
CREATE USER superset WITH PASSWORD 'superset';
CREATE DATABASE superset_meta OWNER superset;
GRANT ALL PRIVILEGES ON DATABASE superset_meta TO superset;
