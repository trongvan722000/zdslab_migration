ARG SUPERSET_VERSION
ARG DRIVER_SOURCE_IMAGE=apachesuperset.docker.scarf.sh/apache/superset:4.1.1-dev

# Source of prebuilt MySQLdb/psycopg2 binaries (same Python 3.10 ABI as the 5.x line) for building in
# networks where apt/pip have no outbound access. No-op on images that already ship both drivers (2.x) —
# the RUN below only copies what's missing and skips entirely once the import check below passes.
FROM ${DRIVER_SOURCE_IMAGE} AS drivers

FROM apache/superset:${SUPERSET_VERSION}

USER root
COPY --from=drivers /usr/local/lib/python3.10/site-packages/MySQLdb /tmp/drivers/MySQLdb
COPY --from=drivers /usr/local/lib/python3.10/site-packages/psycopg2 /tmp/drivers/psycopg2
COPY --from=drivers /usr/local/lib/python3.10/site-packages/psycopg2_binary.libs /tmp/drivers/psycopg2_binary.libs
COPY --from=drivers /usr/lib/x86_64-linux-gnu/libmariadb.so.3 /usr/lib/x86_64-linux-gnu/libmariadb.so.3
COPY --from=drivers /usr/lib/x86_64-linux-gnu/libmariadb.so /usr/lib/x86_64-linux-gnu/libmariadb.so

# The images ship without (all) DB drivers. Superset's MySQL engine spec imports MySQLdb directly, so
# mysqlclient (not just PyMySQL) is needed. 2.x installs into the system Python and already has both
# drivers; 5.x uses a venv (/app/.venv) that pip would not touch, so it goes through uv.
RUN set -e; \
    ldconfig; \
    SITE_PACKAGES=$(python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"); \
    [ -e "$SITE_PACKAGES/MySQLdb" ] || cp -r /tmp/drivers/MySQLdb "$SITE_PACKAGES/MySQLdb"; \
    if [ ! -e "$SITE_PACKAGES/psycopg2" ]; then \
      cp -r /tmp/drivers/psycopg2 "$SITE_PACKAGES/psycopg2"; \
      cp -r /tmp/drivers/psycopg2_binary.libs "$SITE_PACKAGES/psycopg2_binary.libs"; \
    fi; \
    rm -rf /tmp/drivers; \
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

# Extra Python packages the real connections need (e.g. PyMySQL for mysql+pymysql:// URIs). Installed OFFLINE
# from docker/wheels/ (the build network has no DNS/internet): add the package to requirements-local.txt AND put
# its .whl in docker/wheels/ (`pip download --no-deps --only-binary=:all: <pkg>==<ver> -d docker/wheels`).
COPY requirements-local.txt /tmp/requirements-local.txt
COPY wheels/ /tmp/wheels/
RUN set -e; \
    if command -v uv >/dev/null; then \
      uv pip install --no-cache --no-index --find-links /tmp/wheels --python "$(command -v python)" -r /tmp/requirements-local.txt; \
    else \
      pip install --no-cache-dir --no-index --find-links /tmp/wheels -r /tmp/requirements-local.txt; \
    fi; \
    rm -rf /tmp/requirements-local.txt /tmp/wheels
USER superset
