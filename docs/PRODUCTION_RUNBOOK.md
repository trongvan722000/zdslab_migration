# Runbook migrate thật: ZDS Lab 1 → ZDS Lab 2

| | |
|---|---|
| Đọc trước | [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) (lý thuyết, môi trường lab, các bẫy đã gặp). Tài liệu này **không nhắc lại lý thuyết**, chỉ là quy trình làm với hệ thống thật |
| Nguồn | ZDS Lab 1, Superset **2.1.1**. Data: MySQL 10.30.99.7, 8, 9 và Postgres |
| Đích | ZDS Lab 2, Superset **5.0.0**. Data: MySQL 10.30.99.7, 8; Postgres; StarRocks 10.30.99.6, 11, 12 |
| Quy mô Lab 1 | 42 connection, 35 schema, 503 dataset, 160 user (149 active, 11 inactive) |
| Quy mô Lab 2 | 5 connection (đang có người dùng, **phải giữ nguyên**) |
| Phương án | B: export/import + script copy dòng, **thêm vào**, không xoá gì của Lab 2 |
| Trạng thái | Quy trình đã chạy thử trên **lab mô phỏng** (5 connection, 11 chart). **Chưa chạy trên hệ thống thật**; các chỗ chưa kiểm chứng được đánh dấu *(chưa thử)* |

## Mục lục

1. [Nguyên tắc](#1-nguyên-tắc)
2. [Điều chưa biết, phải xác nhận trước](#2-điều-chưa-biết-phải-xác-nhận-trước)
3. [Bộ công cụ: cái nào dùng được ở production](#3-bộ-công-cụ-cái-nào-dùng-được-ở-production)
4. [Giai đoạn 0: Kiểm kê (chỉ đọc)](#4-giai-đoạn-0-kiểm-kê-chỉ-đọc)
5. [Giai đoạn 1: Chuẩn bị điều kiện](#5-giai-đoạn-1-chuẩn-bị-điều-kiện)
6. [Giai đoạn 2: Diễn tập trên bản sao](#6-giai-đoạn-2-diễn-tập-trên-bản-sao)
7. [Giai đoạn 3: Thực hiện thật](#7-giai-đoạn-3-thực-hiện-thật)
8. [Giai đoạn 4: Kiểm chứng](#8-giai-đoạn-4-kiểm-chứng)
9. [Giai đoạn 5: Chuyển người dùng và tắt Lab 1](#9-giai-đoạn-5-chuyển-người-dùng-và-tắt-lab-1)
10. [Rollback](#10-rollback)
11. [Xử lý sự cố](#11-xử-lý-sự-cố)
12. [Bảo mật và dọn dẹp](#12-bảo-mật-và-dọn-dẹp)
13. [Checklist Go / No-Go](#13-checklist-go--no-go)
14. [Phụ lục: mẫu ghi kết quả diễn tập](#14-phụ-lục-mẫu-ghi-kết-quả-diễn-tập)

---

## 1. Nguyên tắc

1. **Lab 1 chỉ bị đọc.** Không bước nào sửa Lab 1 (ngoại lệ duy nhất, có điều kiện: sửa dữ liệu lỗi ở mục 4.4, phải có backup).
2. **Lab 2 chỉ được thêm.** Không xoá, không sửa object có sẵn của Lab 2. Mọi script đều "khớp rồi bỏ qua nếu đã có".
3. **Backup Lab 2 trước khi ghi.** Không có backup thì không bắt đầu.
4. **Diễn tập trên bản sao trước.** Lab mô phỏng có 5 connection; hệ thống thật có 42 connection và 503 dataset. Thời gian, timeout và các dữ liệu "lạ" chỉ lộ ra ở quy mô thật.
5. **Chạy lại được.** Script idempotent (đã thử chạy 2 lần trong lab, lần 2 không tạo trùng). Nhưng: chạy lại `import` sẽ **ghi đè** object có cùng UUID, kể cả khi ai đó đã sửa nó ở Lab 2 sau lần import đầu (mục 7.3).
6. **Mọi bí mật (mật khẩu, `SECRET_KEY`) chỉ tồn tại tạm thời và bị xoá sau khi dùng** (mục 12).

---

## 2. Điều chưa biết, phải xác nhận trước

Tài liệu ZDS LAB chưa nói những điều sau. Chúng quyết định câu lệnh cụ thể, nên phải điền trước khi làm.

| # | Câu hỏi | Vì sao quan trọng | Điền |
|---|---|---|---|
| 1 | Superset Lab 1 / Lab 2 chạy bằng gì: **Docker**, systemd, hay Kubernetes? Tên container/host? | Lệnh trong tài liệu dùng dạng `docker exec <container> ...`; với cách khác phải chạy cùng lệnh trong môi trường Python của Superset | |
| 2 | **Metadata DB** của mỗi Lab nằm ở đâu (host, port, tên database)? Theo trao đổi: Lab 1 ở *zdslab1 MySQL .7*, Lab 2 ở *zdslab2 MySQL .9*. PDF ghi Lab 2 có nguồn dữ liệu MySQL .7, .8 | Cần chuỗi kết nối để copy dòng (user, lịch sử query, cờ xuất bản). Tránh nhầm metadata với **data** khi `mysqldump`/`DROP` | |
| 3 | Kiểu **đăng nhập**: tài khoản trong DB, **LDAP**, hay OAuth/SSO? Cả hai Lab có giống nhau không? | Cách user khớp nhau (mục 4.2). **Import không phụ thuộc đăng nhập** nếu dùng `import_bundle_direct.py` (mục 3.3); chỉ `smoke_test_api.py` và cách import bằng API cần đăng nhập (với LDAP + OTP thì phức tạp) | |
| 4 | `SECRET_KEY` của mỗi Lab lưu ở đâu (file `superset_config.py`, biến môi trường, secret manager)? | `export_db_passwords.py` cần chạy trong môi trường Lab 1 đã nạp đúng key | |
| 5 | Version **chính xác** (`superset version`) và chuỗi **alembic head** của mỗi Lab | Lab 2 phải ≥ Lab 1 | |
| 6 | Có dùng Celery / Redis / cache, nhiều worker, reverse proxy? Timeout của gunicorn và proxy? | Import ZIP lớn có thể bị timeout (mục 7.4) | |
| 7 | Có dùng **Alerts & Reports, RLS, dashboard nhúng, link rút gọn**...? | Những thứ này **không được chuyển** (mục 4.2). Kiểm kê sẽ cho biết | |
| 8 | Ai có quyền: admin Lab 1 và Lab 2, quyền `mysqldump` metadata Lab 2, tài khoản **chỉ đọc** vào metadata Lab 1 | Cần cho các bước | |
| 9 | Lab 2 có kết nối được tới **mọi máy chủ dữ liệu mà Lab 1 dùng** không (đặc biệt MySQL 10.30.99.9 mà Lab 2 chưa dùng) | Nếu không, connection nạp xong vẫn không mở được (mục 5.1) | |
| 10 | Người dùng truy cập Lab 1 qua URL nào (có DNS/alias, có link nhúng ở nơi khác)? | Kế hoạch chuyển người dùng (mục 9) | |

### 2.1. Đã xác nhận trên hệ thống thật (từ người thực hiện)

| Điều | Kết quả | Hệ quả |
|---|---|---|
| Menu Settings của Lab 1 (2.1.1) | Có List Users, List Roles, Row Level Security, Action Log, Database Connections, CSS Templates, Annotation Layers. **Không có Alerts & Reports** | Tính năng Alerts & Reports đang **tắt**: không có gì phải tạo lại (vẫn nên đếm `report_schedule`/`alerts` bằng kiểm kê, mục 4.5) |
| Row Level Security ở Lab 1 | **Không có bản ghi** | Bỏ qua RLS (mục 4.3-C) |
| List Roles ở Lab 1 | **Có role** | Phải xử lý role và quyền của role (mục 4.3-A). Cần biết đó là role tự tạo hay chỉ role mặc định |
| Cách đăng nhập | Mật khẩu là **mã OTP + Google Authenticator** | Import không cần đăng nhập (mục 3.3). Kiểm tra role bằng dữ liệu, không đăng nhập thay người khác được (mục 8.4) |
| Cấu hình đăng nhập (đoạn đã xem) | Có `AUTH_USER_REGISTRATION = True`, `AUTH_USER_REGISTRATION_ROLE = "Gamma"`, `AUTH_ROLES_MAPPING = {"*": [...]}`, `AUTH_ROLE = "Gamma"`; `AUTH_TYPE` **không thấy** trong đoạn | Xem mục 4.6 |

**Vẫn chưa biết:** `AUTH_TYPE` thật, `AUTH_ROLES_SYNC_AT_LOGIN`, Lab 2 có cấu hình giống Lab 1 không, cách triển khai (Docker hay không), vị trí metadata (mục 2).

---

## 3. Bộ công cụ: cái nào dùng được ở production

Các script nằm ở [`fake_data/`](../fake_data/). Thư mục này có **cả script chỉ dành cho lab**; đừng chạy nhầm.

| Script | Dùng ở production? | Chạy ở | Cần |
|---|---|---|---|
| `export_db_passwords.py` | Có, **nhạy cảm** (xuất mật khẩu chữ thường) | **Lab 1** (cần `SECRET_KEY` của Lab 1) | Môi trường app Lab 1 |
| **`import_bundle_direct.py`** (**khuyến nghị, cách duy nhất trong repo**) | Có | Lab 2 | Chỉ môi trường app Lab 2 và tên một user **đã tồn tại** làm owner. **Không cần đăng nhập, OTP, token** |
| `sync_users.py` | Có | Lab 2 | `META_DB_URI`, `SRC_META_URI` |
| `sync_dashboard_published.py` | Có | Lab 2 | như trên |
| `sync_query_history.py` | Có | Lab 2 | như trên |
| `verify_merge.py` | Có (chỉ đọc) | Lab 2 | như trên |
| `check_connections.py` | Có (mở kết nối tới data DB) | Lab 2 | Môi trường app Lab 2 |
| `smoke_test_api.py` | Có, **có giới hạn** (mục 8). **Cần đăng nhập** (gọi API) | Lab 2 | `MAX_CHARTS`, tài khoản, `AUTH_PROVIDER` |
| `sync_users.py` phụ thuộc `seed_fake_metadata.py` | Chỉ **dùng như thư viện** (import hàm `insert`, `find_id`); **không chạy `seed_fake_metadata.py`** | | |
| `seed_fake_metadata.py`, `seed_lab2_existing.py`, `seed_query_history.py` | **KHÔNG.** Tạo dữ liệu giả, chỉ dành cho lab | | |
| `scripts/merge_lab1_to_lab2.sh`, `verify.sh`, `reset_lab2.sh`, `docker-compose.yml` | **KHÔNG.** Viết cho lab Docker (tên container cố định, `reset_lab2.sh` **xoá metadata**) | | |

> Repo từng có thêm `preflight_inventory.py` (kiểm kê chỉ đọc + so sánh Lab 1/Lab 2) và `id_mapping.py` (xuất CSV ánh xạ ID cũ→mới) và `import_bundle.py` (import qua REST API). Cả ba đã bị xoá vì chưa từng chạy trong lúc luyện tập trên lab. Kiểm kê/so sánh ở mục 4 dưới đây làm bằng **SQL trực tiếp** trên metadata; nếu quy mô production (503 dataset, 42 connection) khiến việc này tốn công, cân nhắc viết lại một bản kiểm kê tương tự trước khi migrate thật.

### 3.1. Biến môi trường

Các script `sync_*`, `verify_merge` cần biết **chuỗi kết nối metadata DB**. Trong lab, các container có sẵn biến `META_DB_URI`; ở production container Superset thường **không có** biến này (URI nằm trong `superset_config.py`), nên phải tự khai báo.

Tạo file `migration.env` (quyền `600`, đặt ngoài git, xoá sau khi xong):

```bash
# Đích: metadata DB của Lab 2 (tài khoản có quyền ghi)
META_DB_URI=mysql+mysqldb://<user>:<pass>@<host_meta_lab2>:3306/<db_meta_lab2>?charset=utf8mb4
# Nguồn: metadata DB của Lab 1 (tài khoản CHỈ ĐỌC)
SRC_META_URI=mysql+mysqldb://<user_ro>:<pass>@<host_meta_lab1>:3306/<db_meta_lab1>?charset=utf8mb4
# Địa chỉ Superset Lab 2 NHÌN TỪ BÊN TRONG nơi chạy script
SUPERSET_URL=http://localhost:8088
# db (tài khoản trong DB) hoặc ldap
AUTH_PROVIDER=db
```

- Ký tự đặc biệt trong mật khẩu (`@`, `:`, `/`, `%`) phải **mã hoá URL** (ví dụ `@` → `%40`).
- Lấy nhanh URI hiện tại của một Lab: `python -c "from superset.app import create_app; print(create_app().config['SQLALCHEMY_DATABASE_URI'])"` (in ra cả mật khẩu, cẩn thận).
- Dùng file này với Docker: `docker exec --env-file migration.env <container> python ...`. Với máy không dùng Docker: `set -a; source migration.env; set +a`.

### 3.2. Đưa script vào Lab 2

```bash
docker exec <C2> mkdir -p /tmp/migration_tools
for f in seed_fake_metadata sync_users sync_dashboard_published sync_query_history \
         import_bundle_direct verify_merge check_connections smoke_test_api; do
  docker cp fake_data/$f.py <C2>:/tmp/migration_tools/
done
docker cp fake_data/export_db_passwords.py <C1>:/tmp/
```

(`<C1>`, `<C2>` = container/host chạy Superset Lab 1 / Lab 2.) Các script cần `SQLAlchemy`, `requests`, `PyYAML`, `mysqlclient`, `werkzeug`: **đều có sẵn** trong image Superset. Nếu chạy ngoài container, phải cài đủ.

### 3.3. Đăng nhập, LDAP + OTP: khi nào cần và khi nào không

Phần lớn các bước **không cần đăng nhập** vì chạy thẳng trong ứng dụng hoặc trên database:

| Bước | Cần đăng nhập web/API? |
|---|---|
| Export (`superset export-*`), `export_db_passwords.py` | Không (chạy trong ứng dụng) |
| `sync_users`, `sync_dashboard_published`, `sync_query_history`, `verify_merge` | Không (đọc/ghi thẳng metadata DB) |
| **Import** bằng `import_bundle_direct.py` | **Không.** Gọi lệnh import của Superset ngay trong tiến trình, không qua web |
| `check_connections.py` | Không |
| `smoke_test_api.py` | Có |

**Vì sao đây là điểm quan trọng khi mật khẩu đăng nhập là OTP:** mã OTP đổi mỗi 30 giây và thường dùng một lần, nên script API không tự đăng nhập lặp lại được. Cách import trực tiếp tránh hoàn toàn vấn đề này, và **cũng không dính timeout của proxy/gunicorn** khi ZIP lớn (không có request HTTP nào).

`import_bundle_direct.py` chỉ cần **tên một user đã tồn tại trong Lab 2** làm *owner* của các object nạp vào (tham số thứ ba; mặc định `admin`). Không cần biết mật khẩu của user đó. Nếu user không tồn tại, script dừng ngay với thông báo rõ. Ở production, dùng chính username LDAP của bạn (user phải có sẵn trong Lab 2, ví dụ đã từng đăng nhập hoặc vừa được `sync_users.py` thêm) hoặc một tài khoản admin sẵn có.

**Nếu vẫn phải gọi API** (`smoke_test_api.py`): API đăng nhập của Superset (`/api/v1/security/login`) nhận `provider: ldap` (mật khẩu = OTP) hoặc `provider: db` (mật khẩu lưu trong database Superset, **không qua LDAP/OTP**, đặt `AUTH_PROVIDER=db`). Access token sống **15 phút**, refresh token sống **30 ngày** (`/api/v1/security/refresh`). Tài khoản `db` kiểu dùng chung bỏ qua MFA, cần bộ phận bảo mật đồng ý và ghi nhận. Kết quả này rút ra từ mã nguồn Flask-AppBuilder 4.3.0 và 4.5.5, *chưa thử với LDAP + OTP thật*.

---

## 4. Giai đoạn 0: Kiểm kê (chỉ đọc)

Mục tiêu: biết trước hệ thống thật có gì khác lab, để không bị bất ngờ ở ngày làm.

### 4.1. Chạy kiểm kê

Chạy trên **cả hai** Lab (chỉ đọc, tài khoản `SELECT` là đủ). Câu lệnh viết cho **MySQL**; nếu metadata dùng Postgres phải sửa (`information_schema`, không cần `\`offset\`` backtick).

```sql
-- Version schema (phải khớp/mới hơn giữa hai Lab, xem mục 4.2 dòng đầu)
SELECT version_num FROM alembic_version;

-- User: tổng, không có mật khẩu (nghi LDAP/SSO), chưa đăng nhập, inactive
SELECT COUNT(*) total,
       SUM(password IS NULL OR password = '') no_password,
       SUM(last_login IS NULL) never_login,
       SUM(active = 0) inactive
FROM ab_user;

-- Role không phải mặc định (role tự tạo)
SELECT name FROM ab_role WHERE name NOT IN ('Admin','Alpha','Gamma','Public','sql_lab','granter');

-- Danh sách connection: host, có mật khẩu lưu không
SELECT id, database_name,
       SUBSTRING_INDEX(SUBSTRING_INDEX(sqlalchemy_uri,'@',-1),'/',1) AS host,
       (password IS NOT NULL AND password <> '') AS has_password
FROM dbs;

-- Các thứ KHÔNG được export/import (mục 4.2 giải thích ý nghĩa từng dòng)
SELECT 'report_schedule' t, COUNT(*) n FROM report_schedule
UNION ALL SELECT 'row_level_security_filters', COUNT(*) FROM row_level_security_filters
UNION ALL SELECT 'dashboard_roles', COUNT(*) FROM dashboard_roles
UNION ALL SELECT 'embedded_dashboards', COUNT(*) FROM embedded_dashboards
UNION ALL SELECT 'url', COUNT(*) FROM url
UNION ALL SELECT 'key_value', COUNT(*) FROM key_value
UNION ALL SELECT 'favstar', COUNT(*) FROM favstar
UNION ALL SELECT 'tag', COUNT(*) FROM tag
UNION ALL SELECT 'annotation_layer', COUNT(*) FROM annotation_layer
UNION ALL SELECT 'css_templates', COUNT(*) FROM css_templates
UNION ALL SELECT 'user_attribute', COUNT(*) FROM user_attribute
UNION ALL SELECT 'ssh_tunnels', COUNT(*) FROM ssh_tunnels;

-- Dấu hiệu lỗi dữ liệu: dataset.offset NULL (bẫy #8), dataset/chart mồ côi
SELECT COUNT(*) offset_null FROM tables WHERE `offset` IS NULL;
SELECT COUNT(*) dataset_orphan FROM tables t LEFT JOIN dbs d ON d.id = t.database_id WHERE d.id IS NULL;
SELECT COUNT(*) chart_orphan FROM slices s LEFT JOIN tables t ON t.id = s.datasource_id
  WHERE s.datasource_type = 'table' AND t.id IS NULL;

-- Collation của metadata DB (so với mục 7.1; nhiều collation khác nhau -> bẫy #2 MIGRATION_GUIDE)
SELECT table_collation, COUNT(*) FROM information_schema.tables
  WHERE table_schema = DATABASE() GROUP BY table_collation;
```

**So sánh nguồn/đích** (trùng tên connection, trùng email user, user có ở cả hai nhưng khác role, dashboard sẽ bị ghi đè): chạy cùng câu SQL "danh sách connection" và câu dưới đây trên **cả hai** Lab rồi diff kết quả bằng tay (`diff`/`comm`, hoặc dán vào 2 cột spreadsheet):

```sql
SELECT username, email, GROUP_CONCAT(r.name ORDER BY r.name) roles
FROM ab_user u LEFT JOIN ab_user_role ur ON ur.user_id = u.id LEFT JOIN ab_role r ON r.id = ur.role_id
GROUP BY u.id ORDER BY username;

SELECT uuid, dashboard_title FROM dashboards ORDER BY dashboard_title;   -- uuid trùng giữa 2 Lab -> import sẽ ghi đè
```

> Các câu trên đã chạy thử trên metadata của lab (2.1.1 và 5.0.0), chưa chạy trên hệ thống thật với quy mô 503 dataset / 42 connection — nếu việc diff thủ công quá cồng kềnh ở quy mô đó, cân nhắc viết một script gói lại các câu này (repo từng có `preflight_inventory.py` làm việc này nhưng đã bị xoá vì không được dùng trong lúc luyện tập ở lab).

### 4.2. Đọc kết quả và quyết định

| Phát hiện | Ý nghĩa | Quyết định / hành động |
|---|---|---|
| `alembic head` nguồn ≠ đích, đích cũ hơn | Import từ bản mới sang bản cũ không đảm bảo | Không tiếp tục; xử lý version trước |
| **Users không có mật khẩu** > 0 | Rất có thể đăng nhập bằng LDAP/SSO | Xác nhận Lab 2 dùng **cùng kiểu đăng nhập**. Với LDAP + `AUTH_USER_REGISTRATION=True`, user chưa có sẽ được **tự tạo** lần đăng nhập đầu với role mặc định; user **có role khác mặc định** (Alpha, Admin, role tự tạo) **vẫn phải được chuyển**, nếu không họ mất quyền, và lịch sử query cần user tồn tại để gán. Kiểm tra `AUTH_ROLES_SYNC_AT_LOGIN` ở Lab 2: nếu `True`, role vừa chuyển có thể bị ghi đè về role mặc định ở lần đăng nhập tiếp theo. Với OAuth/SSO, `username` ở hai Lab có thể **khác định dạng** (ví dụ `google_12345` so với email), lúc đó user sẽ bị **nhân đôi** thay vì khớp. Cần thử với 1-2 user thật *(chưa thử)* |
| **User có ở cả hai Lab nhưng khác role** (dòng mới của `compare`) | `sync_users.py` **không sửa** user đã tồn tại | Sửa tay role ở Lab 2 cho từng người (hoặc xoá user đó ở Lab 2 rồi chạy lại `sync_users.py`, chỉ khi user chưa có dữ liệu riêng) |
| **User trùng email nhưng khác username** | `sync_users.py` bỏ qua các user này và in cảnh báo | Xử lý tay từng người (gộp hoặc đổi username) |
| **Role tự tạo** > 0 | User thuộc role đó **mất role**, và role đó thường là thứ cấp **quyền vào từng database/dataset** | Tạo role ở Lab 2 **trước** khi thêm user (mục 7.3a; **phải lọc file**, chỉ import role tự tạo). Quyền vào dataset/database **không chuyển được** bằng `fab import-roles` (tên quyền chứa ID): xem mục 4.3-A |
| `report_schedule` / `alerts` / `*_email_schedules` > 0 | Báo cáo và cảnh báo định kỳ **không được chuyển** | Liệt kê và **tạo lại tay** ở Lab 2. Đây là thứ người dùng dễ phát hiện muộn nhất (báo cáo tự nhiên ngừng gửi) |
| `row_level_security_filters` > 0 | Quy tắc lọc theo dòng **không được chuyển** | Cấu hình lại ở Lab 2 **trước khi mở cho user**, nếu không user có thể thấy dữ liệu không được phép |
| `dashboard_roles` > 0 | Dashboard giới hạn theo role không được chuyển | Cấu hình lại; kiểm tra bằng user thuộc role bị giới hạn |
| `embedded_dashboards` > 0 | Dashboard nhúng ở hệ thống khác sẽ ngừng chạy | Bật lại embedding ở Lab 2 và cập nhật UUID nhúng ở nơi nhúng |
| `url` (link rút gọn) hoặc `key_value` (permalink, filter đã lưu) > 0 | Link cũ do user chia sẻ ngừng hoạt động | Thông báo trước; không có cách chuyển |
| `favstar`, `tag`, `annotation_layer`, `css_templates`, `user_attribute` > 0 | Mất (yêu thích, tag, CSS...) | Chấp nhận hoặc làm tay; báo user |
| `ssh_tunnels` > 0 | Connection đi qua SSH tunnel | Kiểm tra từng connection sau import; có thể phải nhập lại cấu hình/khoá *(chưa thử)* |
| `datasets có offset NULL` > 0 | Import vào 5.0.0 **bị từ chối** (`Field may not be null`) | Sửa mục 4.4 |
| Dataset/chart **trỏ vào object đã xoá** > 0 | Export có thể lỗi hoặc thiếu | Xác định và loại bỏ/sửa trước |
| **Nhiều collation** khác nhau | Lỗi `Illegal mix of collations` với user bị lọc theo quyền | Xem [MIGRATION_GUIDE](MIGRATION_GUIDE.md) Phần V bẫy #2. Áp dụng cho metadata DB **đích**; kiểm tra bằng đăng nhập 1 user Gamma sau khi nạp |
| Connection trùng **tên** nhưng khác UUID | Import báo lỗi | Đổi tên một bên trước |
| Dashboard có cùng UUID ở đích | Sẽ bị **ghi đè** | Chỉ xảy ra nếu đã từng import; chấp nhận nếu chủ ý |
| Connection **không có mật khẩu** | Import vẫn cần điền | Xác định vì sao (dùng SSL cert, IAM, không cần mật khẩu) |

### 4.3. Khoảng trống lớn, đã kiểm chứng ở lab, **chưa có công cụ xử lý**

Ba thứ dưới đây **không đi theo** export/import và đều gây hậu quả thấy được ngay với người dùng. Hai thứ đầu đã được thử thật trên lab (2.1.1 → 5.0.0).

**A. Quyền của role vào database/dataset (quan trọng nhất)**

Người dùng Gamma (và role tự tạo) thường chỉ thấy dữ liệu nhờ các quyền **theo từng đối tượng** gắn vào role, ví dụ `datasource_access` trên `[MySQL - Sales].[orders](id:1)`. Import connection/dataset **không** mang các gán quyền này. Đã thử:

| | Lab 1 | Lab 2 sau merge |
|---|---|---|
| Role `sales_viewer` (quyền vào 2 dataset), gán cho `zds_bob` | Có | **Không có role** (`sync_users.py` cảnh báo `role 'sales_viewer' does not exist`) |
| `zds_bob` thấy | 2 dataset, 1 dashboard | **0 dataset, 0 dashboard** |

Dùng `superset fab export-roles` / `import-roles` cũng **không sửa được**: file export ghi quyền theo *tên có ID* (`[MySQL - Sales].[orders](id:1)`), nhưng ở Lab 2 hai dataset đó có ID khác (`(id:3)`, `(id:4)`), nên quyền vừa nhập trỏ vào đối tượng **không tồn tại** và `zds_bob` (sau khi được gán role) **vẫn thấy 0**. Nguy hiểm hơn: nếu trùng cả tên connection lẫn ID với một dataset khác, quyền có thể **rơi nhầm** sang dataset khác (trong lab tên connection khác nhau nên không xảy ra).

Tên quyền có chứa ID: `datasource_access` (`[db].[table](id:N)`) và `database_access` (`[db].(id:N)`). Quyền theo schema (`[db].[schema]`) không chứa ID nên còn đúng nếu tên connection giữ nguyên.

Cách xử lý:
1. **Đếm quy mô trước:** trên Lab 1, số quyền gắn vào role: chạy `SELECT r.name, COUNT(*) FROM ab_role r JOIN ab_permission_view_role pvr ON pvr.role_id=r.id JOIN ab_permission_view pv ON pv.id=pvr.permission_view_id JOIN ab_view_menu vm ON vm.id=pv.view_menu_id WHERE vm.name LIKE '%(id:%' GROUP BY r.name;`
2. Ít quyền: **tạo lại tay** ở Lab 2 (Settings → List Roles → sửa role → thêm quyền theo tên dataset/database mới).
3. Nhiều quyền: cần **script ánh xạ** (đọc quyền của role ở Lab 1, đổi `(id:N)` sang ID mới ở Lab 2 theo dataset/connection tương ứng qua UUID, rồi gán vào role). *Chưa viết.*

Lưu ý thêm: **role mặc định có bộ quyền khác nhau giữa hai version** (đo ở lab, nguyên bản: 2.1.1 có Admin 204, Alpha 129, Gamma 101, sql_lab 27; 5.0.0 có Admin 161, Alpha 99, Gamma 74, sql_lab 25, vì 5.0.0 đã bỏ/đổi tên nhiều quyền cũ). Vì vậy: (1) dùng bộ quyền của Lab 2 cho role mặc định, **không chép** bộ của Lab 1 sang; (2) nếu người quản trị **đã tự thêm quyền vào role mặc định** ở Lab 1 (ví dụ vào Gamma), so sánh và bổ sung tay **chỉ** phần tuỳ chỉnh; (3) khi chuyển role tự tạo bằng `fab import-roles` phải **lọc file** (chỉ role tự tạo), vì import nguyên file cộng thêm 43 quyền 2.x cũ vào Gamma ở Lab 2 (74 → 117), xem mục 7.3a.

Sau khi xử lý, kiểm tra bằng cách so **danh sách dataset/dashboard mà từng user mẫu thấy** ở Lab 1 và Lab 2 (dùng dữ liệu `ab_user_role` + đăng nhập nhóm thử).

**B. Owner (người tạo) của chart/dashboard/dataset**

Đã thử: dashboard của `zds_david`, `zds_alice`, `zds_frank` ở Lab 1 đều thành owner `admin` ở Lab 2. Với Superset, **người dùng Alpha chỉ sửa được object mình sở hữu** (Admin sửa được tất cả), nên sau migrate họ **mất quyền sửa** dashboard của chính họ. Ảnh hưởng lớn hơn "chỉ hiển thị sai tên". Cách xử lý: map lại owner theo `username` từ `dashboard_user`, `slice_user`, `sqlatable_user` của Lab 1 sang Lab 2 (khớp object theo UUID). *Chưa viết.*

**C. Row Level Security (RLS)**

Không có trong export/import. Nếu Lab 1 đang có RLS (kiểm tra `/rowlevelsecurityfiltersmodelview/list/`) mà Lab 2 không có, user có thể **thấy dòng dữ liệu lẽ ra bị ẩn** (rò rỉ dữ liệu). Bộ lọc tham chiếu **role và dataset bằng ID** nên cũng phải ánh xạ như mục A. Trang trống nghĩa là không có gì phải làm (**đã xác nhận: Lab 1 thật không có bản ghi RLS**, mục này bỏ qua). Nếu có: tạo lại **trước khi mở Lab 2 cho người dùng**.

### 4.4. Sửa dữ liệu lỗi ở Lab 1 (chỉ khi cần, ngoại lệ duy nhất sửa Lab 1)

Ví dụ `offset` NULL (bẫy đã gặp trong lab, xem bẫy #8):

```sql
-- CHỈ sau khi đã backup metadata Lab 1, trong khung giờ thay đổi được duyệt
SELECT COUNT(*) FROM tables WHERE `offset` IS NULL;
UPDATE tables SET `offset` = 0 WHERE `offset` IS NULL;   -- giá trị mà Superset luôn ghi
```

### 4.5. Kiểm tra bằng giao diện (quyền admin)

Dùng khi chưa tiện chạy script. Thêm đường dẫn sau vào địa chỉ Superset (đã xác nhận có ở cả 2.1.1 và 5.0.0):

| Cần xem | Đường dẫn | Menu | Được chuyển? |
|---|---|---|---|
| Alerts (cảnh báo) | `/alert/list/` | Settings → Manage → Alerts & Reports | **Không.** Không thấy menu = tính năng tắt |
| Reports (báo cáo định kỳ) | `/report/list/` | như trên | Không |
| Nhật ký thao tác (log) | `/logmodelview/list/` | Settings → Security → Action Log | Không. Dùng để chọn dashboard xem nhiều (mục 8.3) |
| Lịch sử query của mọi người | `/superset/sqllab/history/` (2.1.1), `/sqllab/history/` (5.0.0) | SQL Lab → Query History | **Có** |
| Query đã lưu | `/savedqueryview/list/` | SQL Lab → Saved Queries | **Có** |
| **Tab SQL Lab đang mở** | (chỉ thấy tab của **chính mình**, admin cũng vậy) | SQL Lab | **Không**, ít quan trọng: user mở tab mới |
| Lọc theo dòng (RLS) | `/rowlevelsecurityfiltersmodelview/list/` (2.1.1), `/rowlevelsecurity/list/` (5.0.0) | Settings → Security → Row Level Security | Không (Lab 1 thật trống) |
| Role, user | List Roles, List Users | Settings → Security | User, role theo tên: có; quyền của role: **không** (4.3-A) |
| CSS template, annotation layer | `/csstemplatemodelview/list/`, `/annotationlayer/list/` | Settings → Manage | Không (đếm; tạo lại tay nếu có) |
| Dashboard nhúng | mở dashboard → menu `...` → Embed dashboard | (từng dashboard) | Không |

Lưu ý: menu ẩn **không** đảm bảo database không còn dữ liệu (ví dụ từng dùng báo cáo định kỳ rồi tắt tính năng). Cách đếm chắc chắn là chạy câu SQL đếm bảng `report_schedule` ở mục 4.1.

### 4.6. Kiểu đăng nhập và cấu hình LDAP

**Cách kiểm tra `AUTH_TYPE` thật** (làm với **cả hai Lab**), từ nhanh đến chắc chắn:
1. Nhìn trang đăng nhập: ô username/password (DB hoặc LDAP), nút "Sign in with ..." (OAuth), vào thẳng không có trang (SSO qua proxy).
2. Đọc `superset_config.py`: `grep -nE "AUTH_|OAUTH_|LDAP" <đường dẫn>`. Không có `AUTH_TYPE` nghĩa là mặc định `AUTH_DB`. Cấu hình có thể nằm ở biến môi trường hoặc file khác (`SUPERSET_CONFIG_PATH`).
3. **Hỏi ứng dụng đang chạy (chắc chắn nhất)**, trong container/máy Lab:

```bash
python - <<'EOF'
from superset.app import create_app
app = create_app()
print("AUTH_TYPE           =", app.config.get("AUTH_TYPE"))        # 1=DB, 2=LDAP, 3=REMOTE_USER, 4=OAUTH, 0=OID
print("AUTH_LDAP_SERVER    =", app.config.get("AUTH_LDAP_SERVER"))
print("OAUTH_PROVIDERS     =", [p.get("name") for p in app.config.get("OAUTH_PROVIDERS", [])])
print("CUSTOM_SECURITY_MGR =", app.config.get("CUSTOM_SECURITY_MANAGER"))
print("AUTH_ROLES_SYNC_AT_LOGIN =", app.config.get("AUTH_ROLES_SYNC_AT_LOGIN"))
print("AUTH_USER_REGISTRATION   =", app.config.get("AUTH_USER_REGISTRATION"), "role:", app.config.get("AUTH_USER_REGISTRATION_ROLE"))
EOF
```
4. Dữ liệu: câu SQL đếm `no_password` ở mục 4.1 (nhiều = nghi LDAP/SSO).

**Phân tích đoạn cấu hình đã xem** (kiểm tra trong mã nguồn Flask-AppBuilder 4.3.0 và 4.5.5):

| Dòng | Đánh giá |
|---|---|
| `#AUTH_TYPE = AUTH_DB` | Bị comment, **không có tác dụng**. Đoạn xem được không có dòng đặt `AUTH_TYPE`: có thể nằm ở nơi khác (nhiều khả năng `AUTH_LDAP` vì có `import AUTH_LDAP`). **Phải xác nhận bằng lệnh ở trên** |
| `AUTH_USER_REGISTRATION = True` | User đăng nhập lần đầu được **tự tạo** trong Superset |
| `AUTH_USER_REGISTRATION_ROLE = "Gamma"` | Role mặc định của user tự tạo |
| `AUTH_ROLE = "Gamma"` | FAB **không dùng biến này** (chỉ dùng `AUTH_ROLE_ADMIN`, `AUTH_ROLE_PUBLIC`, `AUTH_ROLES_MAPPING`, `AUTH_ROLES_SYNC_AT_LOGIN`, `AUTH_USER_REGISTRATION_ROLE`), nên dòng này gần như thừa |
| `AUTH_ROLES_MAPPING = {"*": [...]}` | Mã nguồn FAB **không xử lý ký tự đại diện `*`**; khoá của bảng này được so với tên nhóm của user, nên `"*"` chỉ khớp một nhóm có tên đúng là `*`. Rất có thể **không có tác dụng**. Xác nhận bằng cách xem role thật của một user mới đăng nhập lần đầu |
| `AUTH_ROLES_SYNC_AT_LOGIN` | Mặc định `False` (đã kiểm tra). **Cần xem Lab 2 thật có đặt `True` không**: nếu `True`, role vừa chuyển có thể bị ghi đè lại mỗi lần đăng nhập |

**Ảnh hưởng tới migrate:**
- Với LDAP, user được tìm theo `username`; nếu đã có sẵn ở Lab 2 (do ta chép sang) thì dùng luôn dòng đó, không tạo trùng. Nên `sync_users.py` vẫn phù hợp.
- User chỉ có role mặc định có thể tự đăng ký lại ở Lab 2, nhưng **user có role khác mặc định vẫn phải chuyển**, nếu không họ chỉ nhận Gamma khi đăng nhập lần đầu và mất quyền; lịch sử query cũng cần user tồn tại để gán.
- `username` phải giống hệt giữa hai Lab (cùng trường LDAP như `uid`), nếu không sẽ bị nhân đôi. So sánh 3-5 user bằng câu SQL "so sánh nguồn/đích" ở mục 4.1.
- User đã tự đăng ký ở Lab 2 **trước** khi migrate bị `sync_users.py` bỏ qua (giữ role mặc định); `compare` liệt kê những người khác role (mục 4.2).
- Kiểu đăng nhập của Lab 1 và Lab 2 khác nhau (ví dụ DB so với LDAP) là tình huống **chưa thử**.

---

## 5. Giai đoạn 1: Chuẩn bị điều kiện

### 5.1. Mạng và quyền vào data DB

Sau khi import, **Lab 2 sẽ tự kết nối tới 42 data DB** (cả những cái Lab 2 chưa từng dùng). Có hai lớp chặn thường gặp:

1. **Mạng / firewall:** Lab 2 có thể không tới được một số máy chủ (ví dụ MySQL 10.30.99.9).
2. **Tài khoản DB gắn với địa chỉ nguồn:** tài khoản MySQL kiểu `'reader'@'<IP của Lab 1>'` sẽ từ chối kết nối từ IP của Lab 2 (`Access denied for user ... @ Lab2-IP`). Postgres tương tự qua `pg_hba.conf`.

Kiểm tra **trước** ngày làm:

```bash
# Danh sách host:port mọi connection của Lab 1 (chạy trên metadata Lab 1)
mysql -h <host_meta_lab1> -u <user_ro> -p <db_meta_lab1> -N -e \
 "SELECT DISTINCT SUBSTRING_INDEX(SUBSTRING_INDEX(sqlalchemy_uri,'@',-1),'/',1) FROM dbs"

# Kiểm tra mở được cổng TỪ Lab 2 (dán danh sách host:port vào)
docker exec -i <C2> python - <<'PY'
import socket
for hp in """10.30.99.7:3306
10.30.99.9:3306
<thêm host:port khác>""".split():
    h, p = hp.rsplit(":", 1)
    try:
        socket.create_connection((h, int(p)), timeout=3).close(); print("  OK   ", hp)
    except Exception as e:
        print("  FAIL ", hp, type(e).__name__)
PY

# Tài khoản DB có cho phép IP của Lab 2 không (chạy trên từng data DB)
mysql -h <data_host> -u <admin> -p -e "SELECT user, host FROM mysql.user WHERE user IN ('<reader>')"
```

Kiểm tra mạng chỉ chứng minh cổng mở; **đăng nhập thật** chỉ kiểm chứng được bằng `check_connections.py` sau khi import (mục 8), nên trong diễn tập (mục 6) hãy xem kết quả này kỹ.

Lỗi mở cổng (`FAIL`) hoặc `Access denied` → nhờ người quản lý mạng/DB mở quyền cho IP của Lab 2 **trước**, không phải sau.

### 5.2. Tài khoản và quyền

| Cần | Dùng để | Ghi chú |
|---|---|---|
| Một **user đã tồn tại** trong Lab 2 làm owner của object nạp vào | `import_bundle_direct.py` (tham số thứ ba) | **Không cần mật khẩu/OTP.** Chỉ cần user tồn tại trong `ab_user` của Lab 2 |
| (Chỉ khi dùng API) tài khoản **Admin** đăng nhập được | `smoke_test_api.py` | LDAP + OTP: xem mục 3.3. Hoặc admin tài khoản `db` dùng chung (cần bảo mật duyệt) |
| Tài khoản DB **chỉ đọc** vào metadata Lab 1 (`SELECT`) | `sync_*`, `verify_merge`, câu SQL kiểm kê mục 4.1 | Nếu Lab 2 **không nối được** metadata Lab 1: `mysqldump` các bảng cần (`ab_user`, `ab_role`, `ab_user_role`, `dbs`, `dashboards`, `query`, `saved_query`, `alembic_version`) từ Lab 1 sang một MySQL tạm gần Lab 2 rồi trỏ `SRC_META_URI` vào đó *(chưa thử)* |
| Tài khoản DB **ghi** vào metadata Lab 2 | `sync_*` | Có thể dùng chính tài khoản Superset Lab 2 |
| Quyền `mysqldump` metadata Lab 2 | Backup | |
| Quyền chạy lệnh trong container/host Lab 1 và Lab 2 | Export, `db upgrade`, restart | |
| **Truy cập được `SECRET_KEY` của Lab 1?** | Không cần biết giá trị, nhưng script phải chạy **trong môi trường đã nạp key đó** | Nếu key đã bị đổi kể từ khi lưu mật khẩu connection, không giải mã được (lỗi `ValueError`); khi đó dùng kho mật khẩu công ty |

### 5.3. Mật khẩu 42 connection

Ba nguồn, theo thứ tự ưu tiên (chi tiết ở [MIGRATION_GUIDE](MIGRATION_GUIDE.md) mục 6):
1. **Kho mật khẩu công ty** → lập file JSON `{"<tên connection>": "<mật khẩu>", ...}`. Không giải mã gì trong hệ thống. **Ưu tiên nếu có.**
2. **`export_db_passwords.py`** chạy trong Lab 1: Superset tự giải mã 42 mật khẩu ra file JSON. Nhanh, nhưng tạo ra file **chữ thường**.
3. `DB_PASSWORD` mặc định cho mọi connection dùng chung một mật khẩu (**không hợp với 42 connection thật**, chỉ hợp với lab).

Connection nào không có trong file sẽ rơi về mật khẩu mặc định, sai mật khẩu, và bị 5.0.0 **từ chối ngay** khi nạp dataset (`password authentication failed`). Đó là lưới an toàn, nhưng nghĩa là một mật khẩu sai có thể làm hỏng **cả lần import** (xem 11).

### 5.4. Thời gian, tài nguyên

- Chưa đo trên quy mô thật. Ước lượng chỉ sau khi diễn tập (mục 6, phụ lục mục 14).
- Chuẩn bị chỗ chứa file: ZIP export, dump metadata Lab 2, file mật khẩu. Kích thước ZIP của lab rất nhỏ (~vài chục KB); với 503 dataset sẽ lớn hơn nhưng chưa biết bao nhiêu.
- Import 1 request lớn có thể tốn nhiều phút và vượt timeout (mục 7.4).

---

## 6. Giai đoạn 2: Diễn tập trên bản sao

**Không bỏ qua giai đoạn này.** Mục tiêu: chạy nguyên quy trình mục 7 trên bản sao của Lab 2, để (a) phát hiện lỗi ở quy mô thật, (b) đo thời gian từng bước, (c) chắc chắn quy trình chạy được với 42 connection và 503 dataset.

Nguyên tắc: bản sao Lab 2 phải **giống thật nhất có thể**: cùng version 5.0.0, cùng cấu hình đăng nhập, cùng `SECRET_KEY` (để giải mã được connection cũ), metadata là bản restore từ backup thật.

Bản mẫu (dựa trên repo này, *chưa chạy thử với dữ liệu thật; điều chỉnh cấu hình cho khớp Lab 2 thật*):

```bash
# 1) MySQL tạm
docker network create rehearsal
docker run -d --name rh_mysql --network rehearsal -e MYSQL_ROOT_PASSWORD=<pw> mysql:8.0 --character-set-server=utf8mb4
#    tạo DB metadata với ĐÚNG collation như Lab 2 thật (xem SHOW CREATE DATABASE đã ghi ở mục 7.1)
docker exec -i rh_mysql mysql -uroot -p<pw> -e "CREATE DATABASE superset_meta CHARACTER SET utf8mb4"
docker exec -i rh_mysql mysql -uroot -p<pw> superset_meta < lab2_before_<timestamp>.sql

# 2) Superset 5.0.0 trỏ vào bản sao (image + driver: docker/Dockerfile của repo)
docker build -t superset-rehearsal --build-arg SUPERSET_VERSION=5.0.0 docker/
docker run -d --name rh_superset --network rehearsal -p 18089:8088 \
  -e META_DB_URI='mysql+mysqldb://root:<pw>@rh_mysql:3306/superset_meta?charset=utf8mb4' \
  -e SUPERSET_SECRET_KEY='<SECRET_KEY thật của Lab 2>' \
  -e LAB_NAME=rehearsal \
  -v "$PWD/superset/superset_config.py:/app/pythonpath/superset_config.py:ro" \
  -v "$PWD/superset/bootstrap.sh:/app/docker-init/bootstrap.sh:ro" \
  superset-rehearsal /app/docker-init/bootstrap.sh
```

Cảnh báo cho bản sao:
- **Không chạy Celery/beat** trong bản sao: nếu metadata Lab 2 có báo cáo/cảnh báo định kỳ thì bản sao có thể gửi email/Slack thật.
- Bản sao sẽ **kết nối thật vào data DB** (chỉ đọc) khi kiểm tra connection và chạy chart; chọn khung giờ ít tải.
- `superset/superset_config.py` của repo dùng đăng nhập tài khoản DB, **không giống** cấu hình LDAP/SSO thật. Nếu cần diễn tập đăng nhập thật, dùng bản `superset_config.py` thật của Lab 2 (đổi URI, tắt Alerts & Reports).
- Lab 1 dùng thật (chỉ đọc) làm nguồn, không cần bản sao.

Diễn tập đạt khi:
- [ ] Mọi bước ở mục 7 chạy xong, không lỗi.
- [ ] `verify_merge check` báo `MERGE OK`.
- [ ] `check_connections.py`: **mọi** connection `connect OK` (hoặc có danh sách lý do FAIL đã được xử lý).
- [ ] Đã ghi thời gian từng bước (phụ lục 14) và tổng thời gian.
- [ ] Đã thử rollback (mục 10) trên bản sao và chạy được.
- [ ] Chạy lại lần 2 không tạo bản trùng.
- [ ] Một nhóm nhỏ user thử dùng bản sao.

---

## 7. Giai đoạn 3: Thực hiện thật

Trước khi bắt đầu, tất cả điều kiện mục 13 (Go/No-Go) phải thoả. Ghi thời điểm bắt đầu và kết thúc từng bước.

Quy ước: các lệnh viết cho **Docker**; với môi trường khác, chạy cùng lệnh trong shell đã kích hoạt môi trường Python của Superset. `<C1>` `<C2>` = container/host Lab 1 / Lab 2.

### 7.1. Bước 0: Đóng băng và ghi trạng thái ban đầu

- Thông báo người dùng: trong khung giờ này **không tạo/sửa** dashboard, chart, dataset, connection, user trên **Lab 1** (thay đổi sau lúc export sẽ không được chuyển) và **không sửa các object đã migrate trên Lab 2** (chạy lại import sẽ ghi đè).
- Ghi lại thông tin cần cho rollback:

```bash
# Collation/charset của database metadata Lab 2 (cần khi tạo lại DB lúc rollback)
mysql -h <host_meta_lab2> -u <user> -p -e "SHOW CREATE DATABASE <db_meta_lab2>\G; SELECT @@collation_database;"
# Số lượng ban đầu (chạy các câu SQL kiểm kê ở mục 4.1 trên Lab 2, lưu kết quả lại)
mysql -h <host_meta_lab2> -u <user> -p <db_meta_lab2> -e "SELECT 'users', COUNT(*) FROM ab_user
  UNION ALL SELECT 'connections', COUNT(*) FROM dbs UNION ALL SELECT 'datasets', COUNT(*) FROM tables
  UNION ALL SELECT 'charts', COUNT(*) FROM slices UNION ALL SELECT 'dashboards', COUNT(*) FROM dashboards" \
  | tee lab2_inventory_before.txt
```

### 7.2. Bước 1: Backup Lab 2 (bắt buộc)

```bash
mkdir -p migration_work && cd migration_work

mysqldump -h <host_meta_lab2> -u <user> -p \
  --single-transaction --set-gtid-purged=OFF --routines --triggers \
  <db_meta_lab2> > lab2_before_$(date +%F_%H%M).sql

sha256sum lab2_before_*.sql | tee lab2_before.sha256       # ghi lại để chứng minh bản backup không đổi
ls -l lab2_before_*.sql                                     # kích thước phải hợp lý, không phải 0

# Danh sách những gì Lab 2 đang có ("không được mất")
docker exec --env-file ../migration.env <C2> python /tmp/migration_tools/verify_merge.py snapshot 2>/dev/null > lab2_before.json
```

Kiểm tra bản backup **khôi phục được** (ít nhất trong diễn tập): restore vào MySQL tạm và đếm dòng.

### 7.3. Bước 2: Export từ Lab 1 (chỉ đọc)

```bash
docker exec <C1> superset export-datasources -f /tmp/datasources.zip
docker exec <C1> superset export-dashboards  -f /tmp/dashboards.zip
docker cp <C1>:/tmp/datasources.zip .
docker cp <C1>:/tmp/dashboards.zip  .

ls -l *.zip
unzip -l dashboards.zip | tail -3                 # tổng số file
unzip -l dashboards.zip | grep -c "/databases/"   # phải khớp số connection dùng trong dashboard
unzip -l datasources.zip | grep -c "/datasets/"   # phải bằng số dataset (503)
```

- **Viết đường dẫn `./` hoặc thư mục đích không có dấu `/` đứng đầu**: `/backup` là thư mục ở gốc ổ đĩa.
- Đối chiếu số lượng: nếu số dataset trong ZIP ≠ 503, có object bị bỏ sót (xem preflight: dataset trỏ vào connection đã xoá).
- Thời điểm export là "ảnh chụp": sau đó Lab 1 có thay đổi thì không nằm trong ZIP.

### 7.3a. Bước 2b: Role tự tạo (nếu có), TRƯỚC khi thêm user

`sync_users.py` gán role theo tên và **không tạo role**, nên role tự tạo phải có ở Lab 2 trước bước 7.4. Xuất từ Lab 1, **lọc chỉ giữ role tự tạo và bỏ quyền chứa ID**, rồi import vào Lab 2:

```bash
docker exec <C1> superset fab export-roles --path /tmp/roles.json
docker cp <C1>:/tmp/roles.json - | docker cp - <C2>:/tmp/
docker exec -u root <C2> chown <user_chay_superset> /tmp/roles.json
# lọc bằng đoạn Python ở MIGRATION_GUIDE, Bước 2b (giữ role ngoài BUILTIN, bỏ quyền có "(id:")
docker exec <C2> superset fab import-roles --path /tmp/roles_custom.json
```

- **Không import nguyên file `roles.json`:** đã đo, nó cộng thêm 43 quyền cũ của 2.x vào Gamma ở Lab 2 (74 → 117; Admin +67, Alpha +47, sql_lab +5). File đã lọc thì role mặc định giữ nguyên.
- Quyền vào dataset/database của role phải **cấp lại sau khi import dataset (7.5) và `superset init` (7.8)**, vì dataset chưa tồn tại lúc này (mục 4.3-A).
- Kiểm tra: `SELECT name FROM ab_role;` ở Lab 2 có đủ role tự tạo; số quyền của Gamma/Alpha/Admin/sql_lab không đổi so với trước bước này.

### 7.4. Bước 3: Thêm user

```bash
docker exec --env-file ../migration.env <C2> python /tmp/migration_tools/sync_users.py
```

Kết quả: `added N ...`, `skipped M (already in target)`, `WARN ...` (trùng email, role không tồn tại).
- Khớp theo `username`; user đã có ở Lab 2 **không bị sửa**.
- Chép nguyên chuỗi hash mật khẩu và cờ `active` (user inactive vẫn inactive).
- Chưa quyết định dọn user (ví dụ 11 inactive, 115 active không query 6 tháng)? Bước này chép **tất cả 160**; muốn lọc thì phải sửa script hoặc vô hiệu tài khoản sau đó.
- Xử lý mọi dòng `WARN` trước khi tiếp tục.

**`sync_users.py` ghi vào những bảng nào** (đã đo trên lab bằng cách đếm dòng trước và sau):

| Bảng | Trước → Sau | Ý nghĩa |
|---|---|---|
| `ab_user` | 4 → 12 (+8) | Thêm user (kèm hash mật khẩu, email, `active`) |
| `ab_user_role` | 4 → 12 (+8) | Gán role cho user, **khớp theo tên role** |
| `ab_role` | không đổi | **Không tạo role.** Role phải có sẵn ở Lab 2 (role thiếu → cảnh báo `WARN`, user vẫn được thêm nhưng **không có role đó**) |
| `ab_permission`, `ab_view_menu`, `ab_permission_view` | không đổi | Danh mục quyền, do **Superset tự tạo** (khi khởi động, `superset init`, và khi import dataset). Không gắn với user nên không cần chép |
| `ab_permission_view_role` | không đổi | Quyền gắn vào **role** (không phải vào user). **Không được chép**: xem mục 4.3-A |

Nghĩa là: user vào Lab 2 **đúng tên role**, nhưng role đó **chỉ có tác dụng nếu ở Lab 2 nó có đúng quyền**. Với role mặc định (Gamma, Alpha...) thường ổn; với role tự tạo, quyền phải tạo lại (mục 4.3-A).

Không được chép ở mức user: `last_login` (để `NULL`), `login_count` (đặt 0), `user_attribute` (dashboard chào mừng mặc định), `favstar` (yêu thích). Không ảnh hưởng việc đăng nhập.

**User đã tồn tại ở Lab 2 bị bỏ qua hoàn toàn**, kể cả role. Nếu user đó ở Lab 1 có role khác thì Lab 2 **không được cộng thêm**. Ở production điều này hay xảy ra: user LDAP tự đăng ký ở Lab 2 với role mặc định trước khi bạn migrate. Chạy câu SQL "so sánh nguồn/đích" ở mục 4.1 trên cả hai Lab rồi diff: user có ở cả hai nhưng khác `roles` cho biết chính xác ai cần sửa tay.

Kiểm tra sau khi sync (so role từng user giữa hai Lab: chạy trên mỗi Lab rồi so kết quả):

```sql
SELECT u.username, GROUP_CONCAT(r.name ORDER BY r.name) AS roles, u.active
FROM ab_user u LEFT JOIN ab_user_role ur ON ur.user_id = u.id LEFT JOIN ab_role r ON r.id = ur.role_id
GROUP BY u.id ORDER BY u.username;
```


### 7.5. Bước 4: Import connection, dataset, chart, dashboard

**4a. Chuẩn bị file mật khẩu** (chọn một):

```bash
# (i) Từ kho mật khẩu công ty: tự lập passwords.json {"<tên connection>": "<mật khẩu>", ...}
# (ii) Hoặc để Superset giải mã từ Lab 1:
docker exec <C1> python /tmp/export_db_passwords.py /tmp/passwords.json
#      output cuối: "wrote ...: N passwords exported; M connection(s) without a stored password"
docker cp <C1>:/tmp/passwords.json - | docker cp - <C2>:/tmp/     # container -> container, KHÔNG qua ổ đĩa máy
docker exec -u root <C2> chown <user_chay_superset> /tmp/passwords.json
```

`N` phải bằng số connection (42). `M > 0` nghĩa là có connection không có mật khẩu lưu: xác định vì sao.

**4b. Import (trực tiếp trong container, không đăng nhập):**

```bash
docker cp datasources.zip <C2>:/tmp/ ; docker cp dashboards.zip <C2>:/tmp/
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json <C2> \
  python /tmp/migration_tools/import_bundle_direct.py dataset   /tmp/datasources.zip <owner_username>
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json <C2> \
  python /tmp/migration_tools/import_bundle_direct.py dashboard /tmp/dashboards.zip  <owner_username>
```

`<owner_username>`: user **đã có** trong Lab 2 (mục 3.3). Mỗi lệnh phải in `... import (direct): OK, N connection(s) in bundle` và **không** có dòng `note: no specific password for ...` (nếu có = connection đó đang dùng mật khẩu mặc định).

Kết quả đã thử trên lab (import trực tiếp): mật khẩu **sai** → bị từ chối kèm nguyên nhân gốc (`password authentication failed for user ...`) và **không ghi gì** vào Lab 2; mật khẩu đúng → nạp thành công; chạy lại lần 2 → không tạo trùng; 7/7 connection dùng được.

**Lưu ý: import lại KHÔNG sửa mật khẩu của connection đã tồn tại.** Nếu connection đã nạp với mật khẩu sai, chạy lại import với mật khẩu đúng sẽ **không** đổi mật khẩu đã lưu (đã thử: chạy lại với mật khẩu sai cũng không làm hỏng mật khẩu đúng). Muốn sửa: nhập lại mật khẩu trong giao diện (Settings → Database Connections → Edit), hoặc xoá connection đó và nạp lại.

**4c. Xoá file mật khẩu ngay:**

```bash
docker exec <C1> rm -f /tmp/passwords.json ; docker exec <C2> rm -f /tmp/passwords.json
```

**Import bị timeout (`504`, `502`, treo) khi ZIP lớn** *(chưa gặp trong lab)*: chỉ xảy ra với cách import bằng **API web**. `import_bundle_direct.py` không có request HTTP nên không dính timeout của proxy/gunicorn (nhưng vẫn tốn thời gian thật và giữ một tiến trình lâu). Nếu phải dùng API:
1. Tăng timeout của gunicorn và reverse proxy cho lần import (dùng cấu hình thật của Lab 2), hoặc
2. Chia lô: export theo danh sách ID bằng API (`GET /api/v1/dashboard/export/?q=!(1,2,3)` và `GET /api/v1/dataset/export/?q=!(...)`) rồi import từng lô. Import theo lô an toàn vì UUID; đảm bảo **connection được nạp trước** dashboard (nhập `datasources.zip` trước).

**Lưu ý import lại (chạy lần 2+):** object cùng UUID bị **ghi đè bằng bản Lab 1**. Nếu ai đã sửa object đã migrate ở Lab 2, sửa đổi đó **mất**. Vì vậy chỉ chạy lại khi đã thông báo và chấp nhận điều này.

### 7.6. Bước 5: Khôi phục cờ xuất bản dashboard

```bash
docker exec --env-file ../migration.env <C2> python /tmp/migration_tools/sync_dashboard_published.py
```

Cần vì export từ 2.1.x không chứa trường `published`; không có bước này, user thường (Alpha/Gamma) **không thấy** dashboard đã migrate (bẫy #1). Dashboard không thuộc Lab 1 không bị đụng.

### 7.7. Bước 6: Lịch sử query và saved query

```bash
docker exec --env-file ../migration.env <C2> python /tmp/migration_tools/sync_query_history.py
```

- **Phải chạy sau bước 3 (user) và bước 4 (connection)** vì cần map người chạy theo `username` và database theo tên connection.
- Dòng có connection không tồn tại ở Lab 2 bị bỏ qua và in `WARN`: xem xét từng dòng.
- Chỉ mang phần "nhật ký" (ai, SQL gì, lúc nào, lỗi hay không). **Kết quả đã cache không được mang.**
- Lịch sử 6 tháng qua của Lab 1 (hàng nghìn dòng) là số lượng nhỏ; nhưng chưa đo thời gian ở quy mô thật.

### 7.8. Bước 7: `db upgrade`, `init`, restart Lab 2

```bash
docker exec <C2> superset db upgrade      # no-op nếu schema đã ở head
docker exec <C2> superset init            # tạo permission cho connection/dataset mới
# restart Lab 2 theo cách vận hành thật (docker restart, systemctl restart, rollout restart ...)
```

Restart gây gián đoạn ngắn: thực hiện trong khung giờ đã thông báo. Nếu Lab 2 chạy nhiều worker/replica/Celery, restart **tất cả** thành phần.

---

## 8. Giai đoạn 4: Kiểm chứng

Lab mô phỏng chỉ có 11 chart nên chạy hết được. **Ở thật (503 dataset, hàng trăm chart) đừng chạy toàn bộ chart**: mỗi chart truy vấn data DB thật, một số truy vấn rất chậm (thống kê Lab 1: có truy vấn trung bình 2-3 phút) và có thể gây tải.

### 8.1. Tự động

```bash
# 1) So sánh nguồn/đích theo tên: không mất gì của Lab 2, đủ mọi thứ của Lab 1
docker exec -i --env-file ../migration.env <C2> python /tmp/migration_tools/verify_merge.py check < lab2_before.json
#    Mong đợi: "MERGE OK" và mọi cột "0 | 0"

# 2) Mở thử TỪNG connection (giải mã mật khẩu, kết nối thật)
docker exec --env-file ../migration.env <C2> python /tmp/migration_tools/check_connections.py
#    Mong đợi: 47 dòng connect OK (42 mới + 5 cũ). Mọi FAIL phải được giải thích
```

### 8.2. Mẫu chart có giới hạn (cần đăng nhập)

`smoke_test_api.py` gọi API nên **cần đăng nhập** (LDAP + OTP: xem mục 3.3). Nếu chưa lấy được, bỏ qua bước này và dựa vào 8.1, 8.3 và 8.4 (không phụ thuộc đăng nhập).

```bash
docker exec -e MAX_CHARTS=10 -e AUTH_PROVIDER=<db|ldap> --env-file ../migration.env <C2> \
  python /tmp/migration_tools/smoke_test_api.py http://localhost:8088 <user> '<pass>'
```

Lưu ý: script chỉ lấy **100 chart đầu** (một trang API) và chạy chúng theo thứ tự ID, không phải theo mức dùng thật. Vì vậy hãy **chọn tay** các dashboard quan trọng (8.3).

### 8.3. Chọn dashboard quan trọng và so số liệu

```sql
-- Dashboard được xem nhiều nhất 30 ngày qua, trên metadata Lab 1 (kiểm tra cột dashboard_id tồn tại)
SELECT dashboard_id, COUNT(*) c FROM logs
WHERE dashboard_id IS NOT NULL AND dttm > NOW() - INTERVAL 30 DAY
GROUP BY dashboard_id ORDER BY c DESC LIMIT 20;
```

Với mỗi dashboard trong danh sách (khoảng 10-20 cái), mở ở **cả Lab 1 và Lab 2** và so sánh:
- [ ] Số chart hiển thị bằng nhau.
- [ ] Vài con số chính (KPI, tổng) **giống nhau** (cùng data DB nên phải giống; khác nghĩa là dataset/metric/filter đã đổi).
- [ ] Filter (nội bộ và native) hoạt động.
- [ ] Bố cục không vỡ (2.1.1 → 5.0.0 hiển thị hơi khác là bình thường; chart trống hoặc lỗi thì không).

Kiểm tra này **chỉ làm bằng tay** được; chưa có công cụ tự động so số liệu giữa hai Lab *(chưa làm)*.

### 8.4. Kiểm tra theo người dùng và quyền

Đăng nhập bằng OTP nghĩa là **bạn không đăng nhập thay người khác được**. Kiểm tra role bằng dữ liệu (không cần đăng nhập): `SELECT u.username, r.name FROM ab_user u JOIN ab_user_role ur ON ur.user_id=u.id JOIN ab_role r ON r.id=ur.role_id` so giữa Lab 1 và Lab 2. Việc "đăng nhập thử" dùng **tài khoản của chính bạn** và **nhóm người dùng thử** (mục 9.2) tự đăng nhập và xác nhận.

- [ ] Thử đăng nhập bằng 1 user **mỗi role** đã migrate (Admin, Alpha, Gamma, sql_lab, role tự tạo), bằng chính cách đăng nhập thật (LDAP/SSO nếu có).
- [ ] User Gamma/Alpha thấy **đúng** dashboard, không thấy dashboard không được phép (đặc biệt nếu có RLS / `dashboard_roles`).
- [ ] Một user cũ của Lab 2 vẫn đăng nhập được và vẫn thấy dữ liệu của mình.
- [ ] SQL Lab: chạy 1 query trên connection MySQL và 1 trên Postgres; mở Query History thấy lịch sử cũ.
- [ ] Trang danh sách Database Connections hiển thị với user không phải admin (kiểm tra bẫy collation).

### 8.5. Tiêu chí "xong kỹ thuật"

`MERGE OK` + không còn `FAIL` chưa giải thích + tất cả dashboard quan trọng khớp số liệu + không phát hiện user mất quyền hoặc thấy nhầm dữ liệu.

---

## 9. Giai đoạn 5: Chuyển người dùng và tắt Lab 1

### 9.1. Link và ID

Sau merge, dashboard/chart ở Lab 2 có **ID số mới**. Link dùng **slug** vẫn chạy; link dùng ID cũ (`/superset/dashboard/<id>/`) thì hỏng. Tạo bảng ánh xạ để làm redirect hoặc thông báo:

ID cũ (Lab 1) và ID mới (Lab 2) khớp nhau qua `uuid` (cột này giữ nguyên qua export/import). Xuất riêng từng bên rồi join theo `uuid`:

```bash
# Lab 1 (nguồn, id cũ)
mysql -h <host_meta_lab1> -u <user_ro> -p <db_meta_lab1> -N -e \
  "SELECT HEX(uuid), id, dashboard_title FROM dashboards ORDER BY uuid" | sort > dash_lab1.tsv
# Lab 2 (đích, id mới)
mysql -h <host_meta_lab2> -u <user> -p <db_meta_lab2> -N -e \
  "SELECT HEX(uuid), id, dashboard_title FROM dashboards ORDER BY uuid" | sort > dash_lab2.tsv

join -t $'\t' -1 1 -2 1 -a 1 -e NOT_MIGRATED -o 1.2,2.2,1.3 dash_lab1.tsv dash_lab2.tsv > id_mapping_dashboard.tsv
# cột: old_id, new_id, title ; new_id = NOT_MIGRATED nếu dashboard đó không có ở Lab 2 (bị bỏ sót)
grep NOT_MIGRATED id_mapping_dashboard.tsv
```

Làm tương tự cho `slices` (chart) bằng cách đổi tên bảng và cột (`slice_name` thay `dashboard_title`).

### 9.2. Các bước đề xuất

| Thời điểm | Việc |
|---|---|
| Trước 1-2 tuần | Thông báo kế hoạch, ngày, gián đoạn ngắn; danh sách thứ **không** được chuyển (báo cáo định kỳ, link rút gọn, yêu thích...) |
| Trước ngày làm | Diễn tập xong, đủ điều kiện Go |
| Ngày làm | Mục 7 + 8 |
| Sau ngày làm | Nhóm thử (3-5 user, gồm nhiều role) dùng Lab 2 **1-2 ngày**, báo lỗi |
| Sau đó | Thông báo toàn bộ; đổi DNS/alias/redirect từ URL Lab 1 sang Lab 2 (chú ý **redirect URI của SSO/OAuth** nếu dùng, và các hệ thống khác có link tới Lab 1) |
| Giữ Lab 1 chạy **chỉ đọc/để tham chiếu** | Ít nhất một thời gian thoả thuận (làm điểm lùi). Nói rõ **không tạo mới** ở Lab 1 nữa |
| Sau khi ổn định | Tắt Lab 1 (sau khi chốt thời hạn), dọn connection trùng lặp ở Lab 2 |

### 9.3. Việc làm tay sau khi chuyển

Tuỳ kết quả kiểm kê mục 4: tạo lại báo cáo/cảnh báo định kỳ, cấu hình lại RLS, dashboard theo role, embedding, CSS template, annotation. Kiểm tra lại quyền của **role tự tạo**.

### 9.4. Dọn trùng lặp

Lab 2 đã có 5 connection riêng; Lab 1 có 42. Nếu một số cùng trỏ tới một data DB, sau merge sẽ có **connection trùng mục đích với tên khác nhau**. Không sao về mặt kỹ thuật. Gộp về sau là việc riêng (dataset/chart phải chuyển sang connection còn lại), **không làm trong đợt migrate này**.

---

## 10. Rollback

Chọn theo thời điểm phát hiện vấn đề.

### 10.1. Mức 1: Trước khi mở Lab 2 cho người dùng dùng thật (an toàn nhất)

Khôi phục metadata Lab 2 về đúng bản backup ở bước 1:

```bash
# 1) Dừng Lab 2 (theo cách vận hành thật)
# 2) KIỂM TRA ĐÚNG HOST VÀ TÊN DB. Đây là lệnh xoá. Kiểm tra hai lần, tốt nhất nhờ người thứ hai nhìn.
mysql -h <host_meta_lab2> -u <admin> -p -e "SELECT @@hostname; SHOW DATABASES;"
# 3) Tạo lại DB đúng như lúc đầu (dùng SHOW CREATE DATABASE đã ghi ở 7.1), rồi restore
mysql -h <host_meta_lab2> -u <admin> -p -e "DROP DATABASE <db_meta_lab2>; CREATE DATABASE <db_meta_lab2> CHARACTER SET utf8mb4 COLLATE <collation_ghi_o_7.1>;"
mysql -h <host_meta_lab2> -u <admin> -p <db_meta_lab2> < lab2_before_<timestamp>.sql
sha256sum -c lab2_before.sha256                     # bản dump dùng để restore không bị đổi
# 4) Khởi động Lab 2
# 5) Kiểm tra: số lượng khớp lab2_inventory_before.txt; đăng nhập được; mọi dashboard cũ hiển thị
```

Không ảnh hưởng data DB và không ảnh hưởng Lab 1.

### 10.2. Mức 2: Sau khi người dùng đã dùng Lab 2

Nếu restore bản backup, **mọi thay đổi user đã làm ở Lab 2 kể từ lúc backup sẽ mất**. Các lựa chọn:
- **Lùi hẳn:** đưa người dùng quay lại Lab 1 (vẫn nguyên vẹn nhờ giữ Lab 1 chạy, mục 9.2), rồi xử lý lỗi ở Lab 2 sau. Đây là lý do **không tắt Lab 1 sớm**.
- **Sửa tiến (roll-forward):** sửa từng lỗi cụ thể ở Lab 2 (ví dụ chạy lại `sync_dashboard_published.py`, đổi mật khẩu connection sai) thay vì restore.
- Xoá riêng các object đã import (lùi từng phần): **chưa có công cụ** *(chưa làm)*; có thể tự dựa trên danh sách UUID từ ZIP export, nhưng dễ sai.

### 10.3. Điều kiện quyết định lùi (đề xuất, chốt trước)

Lùi mức 1 nếu: `verify_merge` không `MERGE OK` và không sửa được trong khung giờ; hoặc user cũ của Lab 2 mất quyền/dashboard; hoặc lỗi bảo mật (user thấy dữ liệu không được phép). Ghi cụ thể ngưỡng thời gian cho từng điều kiện trong kế hoạch.

---

## 11. Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Import bị từ chối (`FAILED, nothing was imported`, hoặc `HTTP 500` nếu dùng API), nguyên nhân gốc `password authentication failed` / `Access denied` | Mật khẩu sai, hoặc **tài khoản DB không cho phép IP của Lab 2** | Xem log Lab 2: `docker logs --since 10m <C2> \| grep -iE "authentication\|access denied\|password"`; script direct in sẵn *cause chain* (dòng cuối là nguyên nhân gốc); sửa file mật khẩu hoặc mở quyền IP rồi **chạy lại** import (idempotent, lần bị từ chối không ghi gì). Nếu connection **đã nạp** với mật khẩu sai thì chạy lại không sửa được: nhập lại mật khẩu trong UI (mục 7.5) |
| Import 500, `Can't connect to MySQL server` / `timed out` | Mạng/firewall chặn Lab 2 → data DB | Mở mạng (mục 5.1); chạy lại |
| Import `422`/lỗi validate, `Field may not be null` (thường `offset`) | Dữ liệu cũ ở Lab 1 có NULL | Mục 4.3, export lại |
| Import lỗi vì tên connection trùng | Tên trùng nhưng khác UUID | Đổi tên một bên, chạy lại |
| `504`/`502`, treo | Timeout khi import ZIP lớn | Mục 7.5 (tăng timeout hoặc chia lô) |
| `Permission denied` khi đọc `passwords.json` | `docker cp` giữ quyền `600` của người tạo | `docker exec -u root <C2> chown <user> /tmp/passwords.json` |
| `read-only file system` khi `docker cp` | Đích bắt đầu bằng `/` (gốc ổ đĩa) | Dùng `./` |
| `sync_users.py`: `WARN email ... already used` | User khác username nhưng trùng email | Xử lý tay (gộp/đổi) |
| `sync_users.py`: `WARN role 'X' does not exist` | Role tự tạo chưa có ở Lab 2 (**và role đó có thể mang quyền vào dataset: mục 4.3-A**) | Tạo role và quyền ở Lab 2 rồi chạy lại `sync_users.py` (idempotent nhưng **không gán bổ sung role cho user đã tồn tại**; xem lưu ý) |
| Admin thấy dashboard, user thường thì không | Dashboard chưa xuất bản | `sync_dashboard_published.py` |
| Danh sách Database Connections trống / lỗi 422 với user thường | Collation metadata / role không có quyền xem | Bẫy #2, #3 |
| Chart `FAIL` sau khi nạp nhưng connection OK | Khác hành vi giữa 2.1.1 và 5.0.0 (ví dụ schema Postgres trong SQL Lab, tên cột) | Xem chart cụ thể; sửa dataset/chart ở Lab 2 |
| `sync_query_history.py`: nhiều `WARN ... has no match in target` | Connection bị thiếu ở Lab 2 | Import connection trước; chạy lại |
| `superset db upgrade` lỗi | Cấu trúc metadata Lab 2 bất thường | Dừng, không tiếp tục; xem log, rollback mức 1 nếu cần |
| Warning `Cannot drop column 'druid_datasource_id'` | Cảnh báo đã biết của migration trên MySQL | Bỏ qua |

Lưu ý `sync_users.py`: nếu một user **đã tồn tại** ở Lab 2 thì script bỏ qua hoàn toàn (kể cả role). Nếu sau này mới có role, user đó không được gán thêm; xử lý bằng tay hoặc xoá user đã sync nhầm rồi chạy lại.

---

## 12. Bảo mật và dọn dẹp

| Thứ | Rủi ro | Xử lý |
|---|---|---|
| `passwords.json` | Mật khẩu **chữ thường** của 42 connection | Chỉ tạo trong container, chuyển container → container, **xoá ngay** (7.5 bước 4c). Không để trên máy, không git |
| `migration.env` | Chứa chuỗi kết nối, mật khẩu DB | `chmod 600`, ngoài git, **xoá sau khi xong** |
| Dump metadata (`lab2_before_*.sql`) | Chứa mật khẩu connection **dạng mã hoá** và hash user; đọc được nếu có thêm `SECRET_KEY` | Lưu nơi hạn chế quyền, mã hoá khi lưu; **không lưu chung với `SECRET_KEY`**; đặt thời hạn xoá |
| ZIP export | Không chứa mật khẩu, nhưng chứa cấu trúc dataset/SQL nội bộ | Hạn chế truy cập; xoá sau khi ổn định |
| `SECRET_KEY` | Ai có key + metadata DB thì giải mã được mọi mật khẩu connection | Không ghi vào tài liệu/ticket/chat; không in ra log |
| Tài khoản admin tạm / tài khoản DB tạm | Quyền dư thừa sau migrate | Thu hồi hoặc vô hiệu sau khi xong |
| Công cụ trong container | `/tmp/migration_tools`, `/tmp/*.zip` | `docker exec -u root <C2> sh -c 'rm -rf /tmp/migration_tools /tmp/*.zip'` (chạy bằng root vì file do `docker cp` thuộc user khác, `rm` thường sẽ báo `Operation not permitted`) |
| Lịch sử lệnh terminal | Mật khẩu gõ trực tiếp bị lưu | Dùng file/`--env-file`, không gõ mật khẩu thẳng vào dòng lệnh |
| Quyền chạy `export_db_passwords.py` | Ai chạy được là lấy được mật khẩu | Chỉ người quản trị; ghi lại ai chạy, khi nào |

Cân nhắc **đổi mật khẩu** của các tài khoản data DB sau migrate nếu file mật khẩu từng nằm ở nơi không kiểm soát được.

---

## 13. Checklist Go / No-Go

**Go** chỉ khi **tất cả** đều tích:

Thông tin và điều kiện
- [ ] Mục 2: mọi câu hỏi đã có câu trả lời (đặc biệt #1, #2, #3, #9).
- [ ] Đã chạy kiểm kê (mục 4) và xử lý/quyết định mọi phát hiện.
- [ ] Version Lab 2 ≥ Lab 1; `alembic head` đã ghi.
- [ ] Lab 2 kết nối được tới **mọi** máy chủ data DB; tài khoản DB cho phép IP của Lab 2 (mục 5.1).
- [ ] Đủ mật khẩu cho mọi connection (hoặc quyền chạy `export_db_passwords.py` trong môi trường Lab 1).
- [ ] Có một user **đã tồn tại** trong Lab 2 để làm owner cho `import_bundle_direct.py`; có tài khoản chỉ đọc vào metadata Lab 1. (Chỉ khi dùng API: có cách đăng nhập API, mục 3.3.)

Diễn tập
- [ ] Đã diễn tập trên bản sao Lab 2, đạt toàn bộ tiêu chí (mục 6).
- [ ] Đã ghi thời gian từng bước; tổng thời gian nằm trong khung giờ cho phép, có dự phòng.
- [ ] Đã thử rollback trên bản sao.

Con người
- [ ] Đã duyệt kế hoạch, khung giờ, người thực hiện, người trực rollback.
- [ ] Đã thông báo người dùng: gián đoạn, thứ không được chuyển, đóng băng thay đổi.
- [ ] Đã chốt: giữ owner gốc hay không; chuyển cả user inactive/không hoạt động hay không; thời hạn giữ Lab 1.

Kỹ thuật
- [ ] Backup Lab 2 đã tạo, kích thước hợp lý, `sha256` đã ghi, đã thử restore (ít nhất trên bản sao).
- [ ] Đã ghi `SHOW CREATE DATABASE` của metadata Lab 2.

**No-Go** nếu có bất kỳ mục nào chưa xong, đặc biệt: chưa diễn tập, chưa có backup, chưa kiểm tra mạng tới data DB, chưa rõ kiểu đăng nhập.

---

## 14. Phụ lục: mẫu ghi kết quả diễn tập

Điền khi diễn tập và khi làm thật. Cột "chưa đo" hiện đang trống vì chưa có số liệu thật.

| Bước | Lệnh chính | Thời gian (diễn tập) | Kết quả | Vấn đề gặp / xử lý |
|---|---|---|---|---|
| Kiểm kê | câu SQL mục 4.1 | | | |
| Backup Lab 2 | `mysqldump` | | kích thước: | |
| Export | `export-datasources`, `export-dashboards` | | số dataset/dashboard: | |
| Thêm user | `sync_users.py` | | added / skipped / WARN: | |
| Mật khẩu | file JSON | | N/42: | |
| Import dataset | `import_bundle_direct.py dataset` | | | |
| Import dashboard | `import_bundle_direct.py dashboard` | | | |
| Cờ xuất bản | `sync_dashboard_published.py` | | updated: | |
| Lịch sử query | `sync_query_history.py` | | added / skipped: | |
| `db upgrade` + `init` + restart | | | | |
| `verify_merge` | | | MERGE OK? | |
| `check_connections` | | | OK / FAIL: | |
| So số liệu dashboard quan trọng | thủ công | | khớp: /... | |
| Rollback thử | mục 10.1 | | | |
| **Tổng thời gian** | | | | |

**Ghi chú về những thứ chưa kiểm chứng (từ [MIGRATION_GUIDE](MIGRATION_GUIDE.md) Phần VII và tài liệu này):** chạy trên hệ thống thật; import ở quy mô 503 dataset (timeout, thời gian); role tự tạo (`fab export-roles/import-roles`); đăng nhập LDAP/SSO và khớp username; connection qua SSH tunnel; tài khoản admin tạm với LDAP; chia lô import; nối metadata Lab 1 từ Lab 2 qua MySQL tạm; bản sao diễn tập với cấu hình thật; công cụ so số liệu tự động; công cụ lùi từng phần; giữ owner gốc.
