# Hướng dẫn thực thi: Migrate metadata Superset Lab 1 → Lab 2

> Tài liệu này viết cho **Data Engineer khác** sẽ trực tiếp chạy migration, với giả định bạn đã đọc [RFC_MIGRATION_LAB1_LAB2.md](RFC_MIGRATION_LAB1_LAB2.md) (vấn đề, giải pháp, flow tổng quan). Ở đây **không lặp lại lý thuyết** — chỉ tập trung vào: cần xác nhận gì trước khi bắt đầu, chạy lệnh gì, kiểm chứng ra sao, và làm gì nếu hỏng. Toàn bộ chi tiết/edge case đầy đủ nằm ở [PRODUCTION_RUNBOOK.md](PRODUCTION_RUNBOOK.md) — coi tài liệu đó là *reference*, tài liệu này là *quick path*.

## 0. Trước khi chạy bất kỳ lệnh nào: 6 điều BẮT BUỘC phải xác nhận

Kế hoạch và mọi script trong repo này được xây trên môi trường lab (Docker). Khi đọc `superset_config.py` thật của Lab 1/Lab 2, phát hiện vài điểm **khác với giả định lab**, đủ để đổi cách chạy lệnh. Đừng bắt đầu Giai đoạn 1 nếu chưa có câu trả lời cho bảng này:

| # | Câu hỏi | Vì sao chặn | Dấu hiệu đã thấy |
|---|---|---|---|
| 1 | Superset chạy bằng **Docker, hay cài trực tiếp (conda/pip) trên VM**? | Toàn bộ lệnh mẫu trong repo dùng `docker exec` / `docker cp`. Nếu là bare-metal, phải đổi sang SSH + activate đúng virtualenv | Lab 1 có comment `sys.path.append('/home/<user_he_thong>/anaconda3/envs/zdslab-new/...')` — dấu hiệu cài bằng **conda trên máy chủ**, không phải container |
| 2 | `AUTH_TYPE` thật của **Lab 2** là gì? | Quyết định user có tự đăng ký được không, và role mặc định khi tự đăng ký | File Lab 2 xem được chỉ có `#AUTH_TYPE = AUTH_DB` (bị comment) và import `AUTH_LDAP` không dùng tới — nghĩa là theo đúng file này, `AUTH_TYPE` sẽ rơi về mặc định `AUTH_DB`. Nhưng người yêu cầu migrate xác nhận đăng nhập Lab 2 dùng OTP → khả năng cao còn dòng `AUTH_TYPE = AUTH_LDAP` nằm ở nơi khác (file khác, env var) chưa thấy. **Xác nhận bằng lệnh ở mục 1.1**, đừng suy đoán |
| 3 | Tên database metadata thật + host/port của **Lab 2** | Cần để điền đúng `META_DB_URI` | Lab 1: `mysql+pymysql://...@<db_host_7>/zdslab` (DB tên `zdslab`, driver `pymysql`). Lab 2: **đã xác nhận là Postgres** (không phải MySQL) — driver phải là `psycopg2`; host/port/tên DB thật vẫn cần hỏi lại |
| 4 | `AUTH_ROLES_SYNC_AT_LOGIN` ở Lab 2 có bật không? | Nếu `True`, role vừa migrate cho user có thể bị **ghi đè về mặc định** ngay lần đăng nhập kế tiếp | Không thấy trong file mẫu → có thể chưa set (mặc định `False`), nhưng chưa xác nhận trên máy thật |
| 5 | Cách start/stop/restart Superset (systemd? supervisor? script thủ công?) | Bước cuối cùng (`db upgrade`, `init`, restart) cần đúng lệnh | Chưa biết — hỏi người quản lý hạ tầng |
| 6 | Lab 2 có **kết nối mạng tới toàn bộ 42 data server mà Lab 1 đang dùng** không (đặc biệt server Lab 2 chưa từng dùng)? | Nếu không, connection nạp xong vẫn không dùng được | Chưa kiểm tra |

Cách xác nhận #2, #4 chắc chắn nhất — chạy ngay trong tiến trình Superset đang sống (không cần sửa gì):

```bash
python - <<'EOF'
from superset.app import create_app
app = create_app()
print("AUTH_TYPE               =", app.config.get("AUTH_TYPE"))   # 1=DB 2=LDAP 3=REMOTE_USER 4=OAUTH 0=OID
print("AUTH_LDAP_SERVER         =", app.config.get("AUTH_LDAP_SERVER"))
print("AUTH_ROLES_SYNC_AT_LOGIN =", app.config.get("AUTH_ROLES_SYNC_AT_LOGIN"))
print("SQLALCHEMY_DATABASE_URI  =", app.config.get("SQLALCHEMY_DATABASE_URI"))  # in cả mật khẩu, cẩn thận log
EOF
```

Chạy lệnh này **bên trong** container (nếu Docker) hoặc sau khi `conda activate <env>` (nếu bare-metal) của từng Lab. Chi tiết đầy đủ: [PRODUCTION_RUNBOOK.md §2](PRODUCTION_RUNBOOK.md#2-điều-chưa-biết-phải-xác-nhận-trước), [§4.6](PRODUCTION_RUNBOOK.md#46-kiểu-đăng-nhập-và-cấu-hình-ldap).

## 1. Bản đồ: bước trong RFC → script → chạy ở đâu

| Bước (RFC mục 5) | Script | Chạy ở | Cần đăng nhập web? |
|---|---|---|---|
| 0. Kiểm kê | SQL trực tiếp trên metadata (PRODUCTION_RUNBOOK mục 4.1) | Lab 1 + Lab 2 | Không |
| 1. Backup Lab 2 | `mysqldump` + `verify_merge.py snapshot` | Lab 2 | Không |
| 2. Export connection/dataset/dashboard | `superset export-datasources`, `superset export-dashboards` | Lab 1 | Không |
| 2b. Role tự tạo (nếu có) | `fab export-roles` → lọc → `fab import-roles` | Lab 1 rồi Lab 2 | Không |
| 3. Copy user + role | `sync_users.py` | Lab 2 (đọc chéo sang Lab 1 qua `SRC_META_URI`) | Không |
| 4. Import connection/dataset/dashboard | `export_db_passwords.py` (Lab 1) rồi `import_bundle_direct.py` (Lab 2) | Lab 1 → Lab 2 | **Không** |
| 5. Vá cờ published | `sync_dashboard_published.py` | Lab 2 | Không |
| 6. Copy lịch sử query | `sync_query_history.py` | Lab 2 | Không |
| 7. Upgrade & restart | `superset db upgrade`, `superset init`, restart service | Lab 2 | — |
| 8. Kiểm chứng | `verify_merge.py check`, `check_connections.py`, đăng nhập thử vài user | Lab 2 | Có (chỉ để soi bằng mắt) |

Điểm quan trọng nhất: **không có bước nào (trừ soi lại bằng mắt ở cuối) cần đăng nhập qua web/API** — mọi thứ chạy thẳng vào database metadata hoặc gọi lệnh Superset trong tiến trình. Đây là lý do bỏ qua được vấn đề LDAP + OTP khi tự động hoá.

## 2. Chuẩn bị

### 2.1. `migration.env` (không commit, quyền `600`, xoá sau khi xong)

```bash
META_DB_URI=postgresql+psycopg2://<user_ghi>:<pass>@<host_meta_lab2>:5432/<db_meta_lab2>
SRC_META_URI=mysql+pymysql://<user_chi_doc>:<pass>@<host_meta_lab1>:3306/zdslab?charset=utf8mb4
```

**Hai Lab khác cả driver:** Lab 2 (Postgres) cần `psycopg2`; Lab 1 (MySQL) cần `pymysql` (theo config thật đã xem — **không phải** `mysqlclient` như trong lab). Cài thư viện tương ứng vào môi trường sẽ chạy script nếu chưa có (`pip install psycopg2-binary pymysql` hoặc tương đương trong conda env).

### 2.2. Đưa script vào máy chạy Lab 1 / Lab 2

Docker: `docker cp fake_data/<script>.py <container>:/tmp/`.
Bare-metal: `scp fake_data/<script>.py <host>:/tmp/`, rồi chạy bằng đúng interpreter (`/home/<user_he_thong>/anaconda3/envs/zdslab-new/bin/python /tmp/<script>.py`, hoặc `conda activate zdslab-new && python /tmp/<script>.py`).

Script cần: `SQLAlchemy`, `requests`, `PyYAML`, `pymysql`/`mysqlclient` (cho Lab 1), `psycopg2` (cho Lab 2), `werkzeug` — đều là dependency có sẵn của Superset nên nếu chạy **trong đúng virtualenv của Superset** sẽ có sẵn (Lab 2 vốn đã cần `psycopg2` để tự kết nối metadata của chính nó).

**Không đưa vào production:** `seed_fake_metadata.py`, `seed_lab2_existing.py`, `seed_query_history.py` (tạo dữ liệu giả), `docker-compose.yml`, `scripts/*.sh` (viết cứng cho container lab).

## 3. Chạy — theo đúng thứ tự

> Toàn bộ lệnh dưới viết dạng Docker (`docker exec <C> ...`). Nếu bare-metal, thay bằng `ssh <host> '<đường dẫn python của venv> /tmp/<script>.py'` (giữ nguyên tham số và biến môi trường, đặt trước lệnh bằng `export`).

```bash
# --- Bước 0: kiểm kê, không sửa gì (câu SQL đầy đủ: PRODUCTION_RUNBOOK.md mục 4.1) ---
mysql -h <host_meta_lab1> -u <user_ro> -p <db_meta_lab1> -e "SELECT COUNT(*) FROM ab_user; SELECT COUNT(*) FROM dbs;"
psql -h <host_meta_lab2> -U <user> -d <db_meta_lab2> -c "SELECT COUNT(*) FROM ab_user; SELECT COUNT(*) FROM dbs;"

# --- Bước 1: backup Lab 2 (bắt buộc, không có thì dừng) — Lab 2 là Postgres, dùng pg_dump ---
pg_dump -h <host_meta_lab2> -U <user> --no-owner \
  <db_meta_lab2> > lab2_before_$(date +%F_%H%M).sql
docker exec --env-file migration.env <C2> python /tmp/verify_merge.py snapshot > lab2_before.json

# --- Bước 2: export từ Lab 1 (chỉ đọc) ---
docker exec <C1> superset export-datasources -f /tmp/datasources.zip
docker exec <C1> superset export-dashboards  -f /tmp/dashboards.zip
docker cp <C1>:/tmp/datasources.zip . ; docker cp <C1>:/tmp/dashboards.zip .

# --- Bước 2b: role tự tạo (bỏ qua nếu preflight không thấy role tự tạo) ---
docker exec <C1> superset fab export-roles --path /tmp/roles.json
docker cp <C1>:/tmp/roles.json - | docker cp - <C2>:/tmp/
# lọc: giữ role NGOÀI {Admin,Alpha,Gamma,Public,sql_lab,granter}, bỏ quyền có "(id:" trong tên
# -> script lọc có sẵn ở MIGRATION_GUIDE.md, Bước 2b
docker exec <C2> superset fab import-roles --path /tmp/roles_custom.json

# --- Bước 3: user + role-của-user ---
docker exec --env-file migration.env <C2> python /tmp/sync_users.py

# --- Bước 4: mật khẩu + import connection/dataset/dashboard ---
docker exec <C1> python /tmp/export_db_passwords.py /tmp/passwords.json
docker cp <C1>:/tmp/passwords.json - | docker cp - <C2>:/tmp/
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json <C2> python /tmp/import_bundle_direct.py dataset   /tmp/datasources.zip <owner_username_co_san_o_lab2>
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json <C2> python /tmp/import_bundle_direct.py dashboard /tmp/dashboards.zip  <owner_username_co_san_o_lab2>
docker exec <C1> rm -f /tmp/passwords.json ; docker exec <C2> rm -f /tmp/passwords.json   # xoá ngay

# --- Bước 5: vá cờ published ---
docker exec --env-file migration.env <C2> python /tmp/sync_dashboard_published.py

# --- Bước 6: lịch sử query ---
docker exec --env-file migration.env <C2> python /tmp/sync_query_history.py

# --- Bước 7: upgrade + restart Lab 2 (đổi lệnh restart theo #5 ở mục 0) ---
docker exec <C2> superset db upgrade
docker exec <C2> superset init
docker compose restart superset_lab2   # HOẶC: systemctl restart <service> / lệnh của hạ tầng thật

# --- Bước 8: kiểm chứng ---
docker exec --env-file migration.env <C2> python /tmp/verify_merge.py check
docker exec --env-file migration.env <C2> python /tmp/check_connections.py
```

Mỗi lệnh in kết quả có thể đối chiếu (`OK`, `added N`, `skipped M`, `WARN ...`) — **dừng lại và đọc kỹ dòng `WARN`/lỗi trước khi sang bước kế tiếp**, đừng chạy hết một mạch rồi mới kiểm tra.

## 4. Sau khi chạy xong: những gì KHÔNG tự động, phải làm tay

Đọc kỹ [PRODUCTION_RUNBOOK.md §4.3](PRODUCTION_RUNBOOK.md#43-khoảng-trống-lớn-đã-kiểm-chứng-ở-lab-chưa-có-công-cụ-xử-lý) — tóm tắt 3 việc lớn nhất:

1. **Quyền role vào từng dataset/database** (`datasource_access`, `database_access`) không đi theo import → user role tự tạo/Gamma có thể thấy **0 dataset** dù connection đã có. Cấp lại tay sau khi import xong.
2. **Owner** của dashboard/chart/dataset đổi hết thành user chạy import → user Alpha mất quyền sửa dashboard của chính mình. Map lại owner theo username nếu cần (chưa có script, làm tay qua UI hoặc viết thêm).
3. Nếu preflight ở Bước 0 phát hiện có **Alerts & Reports / RLS / dashboard nhúng / báo cáo định kỳ** đang dùng thật (khác với Lab 1 mẫu, nơi các mục này trống) — các thứ này không chuyển được, phải cấu hình lại tay ở Lab 2 **trước khi mở cho người dùng**.

## 5. Rollback

```bash
# dừng Lab 2, restore lại đúng bản backup ở Bước 1 (Postgres)
psql -h <host_meta_lab2> -U <admin> -d postgres -c "DROP DATABASE <db_meta_lab2>;"
psql -h <host_meta_lab2> -U <admin> -d postgres -c "CREATE DATABASE <db_meta_lab2> OWNER <owner_ban_dau>;"
psql -h <host_meta_lab2> -U <admin> -d <db_meta_lab2> -f lab2_before_<timestamp>.sql
# khởi động lại Lab 2
```

Không có gì trong quy trình này sửa Lab 1 (trừ trường hợp ngoại lệ đã ghi rõ ở PRODUCTION_RUNBOOK §4.4), nên Lab 1 luôn giữ nguyên làm nguồn nếu cần chạy lại.

## 6. Khi gặp lỗi

Tra theo thông báo lỗi ở [PRODUCTION_RUNBOOK.md §11 Xử lý sự cố](PRODUCTION_RUNBOOK.md#11-xử-lý-sự-cố). Nếu lỗi không có trong đó: dừng lại, không đoán và chạy tiếp — báo lại người đã viết tài liệu này kèm log đầy đủ của lệnh bị lỗi.
