ARG SUPERSET_VERSION
FROM apache/superset:${SUPERSET_VERSION}

USER root
# The images ship without (all) DB drivers. Superset's MySQL engine spec imports MySQLdb directly, so
# mysqlclient (not just PyMySQL) is needed. 2.x installs into the system Python and already has both
# drivers; 5.x uses a venv (/app/.venv) that pip would not touch, so it goes through uv.
RUN set -e; \
    if python -c "import MySQLdb, psycopg2" 2>/dev/null; then echo "DB drivers already present"; exit 0; fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential default-libmysqlclient-dev pkg-config; \
    if command -v uv >/dev/null; then \
      uv pip install --no-cache --python "$(command -v python)" psycopg2-binary mysqlclient; \
    else \
      pip install --no-cache-dir psycopg2-binary mysqlclient; \
    fi; \
    apt-get purge -y build-essential pkg-config; apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*
USER superset
