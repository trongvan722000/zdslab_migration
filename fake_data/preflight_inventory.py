"""READ-ONLY inventory of a Superset metadata DB (MySQL), for planning a migration. Safe to run on production.

Run it inside an environment where META_DB_URI points at the metadata DB you want to inspect (a Superset
container / venv), or pass the URI explicitly:

    python preflight_inventory.py                       # inspect META_DB_URI
    python preflight_inventory.py <sqlalchemy-uri>      # inspect another metadata DB
    SRC_META_URI=<lab1-uri> python preflight_inventory.py compare
        # inspect META_DB_URI (target) and report conflicts against SRC_META_URI (source)

It never writes. Use a read-only DB account.
"""
import os
import re
import sys
from collections import Counter

from sqlalchemy import create_engine, inspect, text

MODE = "compare" if len(sys.argv) > 1 and sys.argv[1] == "compare" else "inspect"
URI = os.environ["META_DB_URI"] if MODE == "compare" or len(sys.argv) < 2 else sys.argv[1]
SRC_URI = os.environ.get("SRC_META_URI")
if MODE == "compare" and not SRC_URI:
    sys.exit("compare needs SRC_META_URI (sqlalchemy URI of the SOURCE metadata DB, read-only account)")

BUILTIN_ROLES = {"Admin", "Alpha", "Gamma", "Public", "sql_lab", "granter"}  # granter: built-in of Superset 2.x

# Things this migration does NOT carry over. If a count is > 0 the migration plan needs a decision for it.
NOT_MIGRATED = [
    ("report_schedule", "báo cáo / cảnh báo định kỳ (Alerts & Reports)"),
    ("alerts", "cảnh báo kiểu cũ (2.x)"),
    ("dashboard_email_schedules", "lịch gửi email dashboard (kiểu cũ)"),
    ("slice_email_schedules", "lịch gửi email chart (kiểu cũ)"),
    ("row_level_security_filters", "bộ lọc theo dòng (RLS)"),
    ("dashboard_roles", "dashboard giới hạn theo role"),
    ("embedded_dashboards", "dashboard nhúng (embedded)"),
    ("favstar", "dashboard/chart yêu thích của user"),
    ("annotation_layer", "annotation layer"),
    ("css_templates", "CSS template"),
    ("tag", "tag"),
    ("url", "link rút gọn đã chia sẻ (bảng url)"),
    ("key_value", "permalink / trạng thái filter đã lưu"),
    ("filter_sets", "filter set (2.x)"),
    ("ssh_tunnels", "SSH tunnel của connection"),
    ("user_attribute", "thuộc tính user (dashboard mặc định...)"),
    ("tab_state", "tab SQL Lab đang mở"),
]


def q(conn, sql, **kw):
    return conn.execute(text(sql), kw)


def inventory(uri, label):
    engine = create_engine(uri)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    print(f"\n{'=' * 78}\n{label}: {re.sub(r':[^:@/]+@', ':***@', uri)}\n{'=' * 78}")
    with engine.connect() as c:
        head = q(c, "SELECT version_num FROM alembic_version").scalar()
        print(f"schema (alembic head): {head}")
        print(f"MySQL: {q(c, 'SELECT VERSION()').scalar()}, default collation: "
              f"{q(c, 'SELECT @@collation_database').scalar()}")

        print("\n-- Số lượng object --")
        for name, sql in [
            ("users (tổng)", "SELECT COUNT(*) FROM ab_user"),
            ("  users active", "SELECT COUNT(*) FROM ab_user WHERE active = 1"),
            ("  users KHÔNG có mật khẩu (nghi dùng LDAP/SSO)", "SELECT COUNT(*) FROM ab_user WHERE password IS NULL OR password = ''"),
            ("  users chưa từng đăng nhập", "SELECT COUNT(*) FROM ab_user WHERE last_login IS NULL"),
            ("connections (dbs)", "SELECT COUNT(*) FROM dbs"),
            ("datasets (tables)", "SELECT COUNT(*) FROM tables"),
            ("charts (slices)", "SELECT COUNT(*) FROM slices"),
            ("dashboards", "SELECT COUNT(*) FROM dashboards"),
            ("  dashboards published", "SELECT COUNT(*) FROM dashboards WHERE published = 1"),
            ("query history", "SELECT COUNT(*) FROM query"),
            ("saved queries", "SELECT COUNT(*) FROM saved_query"),
        ]:
            print(f"  {name:<46} {q(c, sql).scalar()}")

        print("\n-- Connections --")
        for name, uri_, has_pw in q(c, "SELECT database_name, sqlalchemy_uri, (password IS NOT NULL) FROM dbs ORDER BY id"):
            m = re.match(r"^([\w+]+)://[^@]*@?([^/]*)/?(.*)$", uri_ or "")
            backend, host, db = (m.groups() if m else ("?", "?", "?"))
            print(f"  {name[:34]:<34} {backend:<22} {host:<26} {db[:20]:<20} {'pw' if has_pw else 'NO PASSWORD'}")

        print("\n-- Role tự tạo (ngoài Admin/Alpha/Gamma/Public/sql_lab/granter) --")
        rows = q(c, "SELECT r.name, COUNT(ur.user_id) FROM ab_role r LEFT JOIN ab_user_role ur ON ur.role_id = r.id GROUP BY r.id, r.name ORDER BY r.name").all()
        custom = [(n, k) for n, k in rows if n not in BUILTIN_ROLES]
        print("  " + (", ".join(f"{n} ({k} user)" for n, k in custom) if custom else "(không có)"))

        print("\n-- Thứ KHÔNG được migrate mà hệ thống này đang dùng --")
        found = False
        for tbl, desc in NOT_MIGRATED:
            if tbl in tables:
                n = q(c, f"SELECT COUNT(*) FROM `{tbl}`").scalar()
                if n:
                    found = True
                    print(f"  {tbl:<28} {n:>7}   {desc}")
        if not found:
            print("  (không có)")

        print("\n-- Dấu hiệu lỗi dữ liệu có thể làm import thất bại --")
        print(f"  datasets có offset NULL           : {q(c, 'SELECT COUNT(*) FROM tables WHERE `offset` IS NULL').scalar()}   (Superset 5.x import từ chối NULL)")
        print(f"  datasets trỏ vào connection đã xoá: {q(c, 'SELECT COUNT(*) FROM tables t LEFT JOIN dbs d ON d.id = t.database_id WHERE d.id IS NULL').scalar()}")
        print(f"  chart trỏ vào dataset đã xoá      : {q(c, 'SELECT COUNT(*) FROM slices s LEFT JOIN tables t ON t.id = s.datasource_id WHERE s.datasource_id IS NOT NULL AND t.id IS NULL').scalar()}")
        dup = q(c, "SELECT database_name, COUNT(*) FROM dbs GROUP BY database_name HAVING COUNT(*) > 1").all()
        print(f"  tên connection bị trùng           : {dup or 0}")
        colls = Counter(r[0] for r in q(c, "SELECT DISTINCT collation_name FROM information_schema.columns WHERE table_schema = DATABASE() AND collation_name IS NOT NULL").all())
        colls = sorted(colls)
        flag = "   <-- NHIỀU collation khác nhau, xem tài liệu (bẫy collation)" if len(colls) > 1 else ""
        print(f"  collation các cột                 : {', '.join(colls)}{flag}")
    return engine


def compare(target_uri, source_uri):
    tgt, src = create_engine(target_uri), create_engine(source_uri)
    print(f"\n{'=' * 78}\nSO SÁNH nguồn (SRC_META_URI) và đích (META_DB_URI)\n{'=' * 78}")
    with tgt.connect() as t, src.connect() as s:
        s_head = q(s, "SELECT version_num FROM alembic_version").scalar()
        t_head = q(t, "SELECT version_num FROM alembic_version").scalar()
        print(f"alembic head nguồn = {s_head}, đích = {t_head}"
              f"{'   (giống nhau)' if s_head == t_head else '   (KHÁC: đích phải là bản mới hơn hoặc bằng nguồn)'}")

        s_db = {r[0]: r[1] for r in q(s, "SELECT database_name, HEX(uuid) FROM dbs")}
        t_db = {r[0]: r[1] for r in q(t, "SELECT database_name, HEX(uuid) FROM dbs")}
        clash = sorted(n for n in s_db if n in t_db and s_db[n] != t_db[n])
        print(f"\nConnection trùng TÊN nhưng khác UUID (import sẽ lỗi, cần đổi tên một bên): {len(clash)}")
        for n in clash:
            print(f"  - {n}")

        s_u = {r[0]: r[1] for r in q(s, "SELECT username, email FROM ab_user")}
        t_u = {r[0]: r[1] for r in q(t, "SELECT username, email FROM ab_user")}
        t_email = {e: u for u, e in t_u.items()}
        same = sorted(u for u in s_u if u in t_u)
        mail_clash = sorted((u, t_email[e]) for u, e in s_u.items() if u not in t_u and e in t_email)
        print(f"\nUser trùng username (giữ nguyên bản của đích, KHÔNG sửa): {len(same)}")
        ROLES_SQL = ("SELECT u.username, r.name FROM ab_user u JOIN ab_user_role ur ON ur.user_id = u.id "
                     "JOIN ab_role r ON r.id = ur.role_id")
        def roles_by_user(conn):
            out = {}
            for uname, rname in q(conn, ROLES_SQL):
                out.setdefault(uname, set()).add(rname)
            return out
        s_roles, t_roles = roles_by_user(s), roles_by_user(t)
        differ = sorted(u for u in same if s_roles.get(u, set()) != t_roles.get(u, set()))
        print(f"User có ở CẢ HAI nhưng KHÁC role (sync_users.py KHÔNG sửa user đã tồn tại, phải xử lý tay): {len(differ)}")
        for u in differ[:25]:
            print(f"  - {u}: nguồn={sorted(s_roles.get(u, set())) or '-'}  đích={sorted(t_roles.get(u, set())) or '-'}")
        if len(differ) > 25:
            print(f"  ... và {len(differ) - 25} user nữa")
        print(f"User khác username nhưng trùng email (sẽ bị bỏ qua, cần xử lý tay): {len(mail_clash)}")
        for u, other in mail_clash:
            print(f"  - {u}  (email trùng với user '{other}' ở đích)")
        print(f"User chỉ có ở nguồn (sẽ được thêm): {len([u for u in s_u if u not in t_u and u not in dict(mail_clash)])}")

        s_r = {r[0] for r in q(s, "SELECT name FROM ab_role")}
        t_r = {r[0] for r in q(t, "SELECT name FROM ab_role")}
        miss = sorted((s_r - t_r) - BUILTIN_ROLES)
        print(f"\nRole có ở nguồn nhưng chưa có ở đích (user thuộc role này sẽ mất role): {miss or 'không có'}")

        s_dash = {r[0] for r in q(s, "SELECT HEX(uuid) FROM dashboards")}
        t_dash = {r[0] for r in q(t, "SELECT HEX(uuid) FROM dashboards")}
        print(f"\nDashboard đã có cùng UUID ở đích (sẽ bị GHI ĐÈ bằng bản nguồn): {len(s_dash & t_dash)}")


if __name__ == "__main__":
    if MODE == "compare":
        inventory(URI, "ĐÍCH (META_DB_URI)")
        compare(URI, SRC_URI)
    else:
        inventory(URI, "METADATA")
