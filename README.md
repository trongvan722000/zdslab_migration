# ZDS Lab: merge metadata Superset Lab 1 vào Lab 2

> **Tài liệu đầy đủ (lý thuyết, bẫy đã gặp, áp dụng production): [docs/MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md).** File này là hướng dẫn thao tác nhanh. **Migrate thật: [docs/PRODUCTION_RUNBOOK.md](docs/PRODUCTION_RUNBOOK.md).**

Mục tiêu: chuyển **metadata** (connection, dataset, chart, dashboard, user, lịch sử query SQL Lab, saved query) từ Lab 1 sang Lab 2 theo kiểu **thêm vào**.
Những gì Lab 2 đang có (user, connection, dataset, dashboard riêng) vẫn được giữ nguyên.
Data thật (MySQL `sales`, `crm`; Postgres `finance`, `warehouse`, `marketing`) không di chuyển: cả 2 lab cùng truy vấn vào đó.

## 1. Kiến trúc

| Container | Vai trò | Truy cập |
|---|---|---|
| `superset_lab1` | Superset nguồn **2.1.1**. Metadata lưu ở `mysql_lab1` (**MySQL**) | http://localhost:8088 |
| `superset_lab2` | Superset đích **5.0.0**. Metadata lưu ở `postgres_lab2` (**Postgres**) | http://localhost:8089 |
| `mysql_lab1` | Metadata Lab 1 (`superset_meta`, MySQL) + data `sales`, `crm` | localhost:3307 |
| `postgres_lab1` | Data `finance`, `warehouse`, `marketing` (không phải metadata) | localhost:5433 |
| `postgres_lab2` | Metadata Lab 2 (`superset_meta`, **Postgres**) | localhost:5434 |

> **Hai lab khác cả version lẫn loại database metadata:** Lab 1 lưu metadata trên MySQL, Lab 2 trên Postgres — đúng như môi trường thật (`zdslab1` MySQL, `zdslab2` Postgres). Đây là lý do một số script (`sync_dashboard_published.py`, `sync_query_history.py`, `verify_merge.py`) phải tự nhận diện dialect khi so khớp cột `uuid`/kiểu boolean giữa hai bên — xem mục 7.

> **Hai lab khác version (2.1.1 → 5.0.0).** Đổi bằng biến môi trường `SUPERSET_VERSION_LAB1` / `SUPERSET_VERSION_LAB2` (mặc định 2.1.1 và 5.0.0).
> Image 2.1.1 chỉ có bản amd64, nên trên máy Apple Silicon `superset_lab1` chạy giả lập: khởi động chậm hơn (lần đầu vài phút) nhưng vẫn chạy bình thường.
> Vì khác version nên schema metadata của hai bên khác nhau (alembic head khác nhau). Đây là lý do dùng export/import: dump/restore giữa hai version không dùng được.

Tài khoản:

| | user / password |
|---|---|
| Admin (cả 2 lab) | `admin` / `admin` |
| User của Lab 1 | `zds_alice` (Alpha), `zds_bob`, `zds_carol`, `zds_emma`, `zds_grace` (Gamma), `zds_david` (sql_lab), `zds_frank` (Alpha), `zds_henry` (Admin), mật khẩu `Passw0rd!` |
| User có sẵn của Lab 2 | `lab2_nam` (Alpha), `lab2_linh` (Gamma), `lab2_hung` (Admin), mật khẩu `Lab2Passw0rd!` |
| MySQL root (`mysql_lab1`) | `root` / `root` |
| Postgres superuser (`postgres_lab1`, `postgres_lab2`) | `postgres` / `postgres` |
| Metadata DB (cả MySQL lẫn Postgres) | `superset` / `superset` |
| Read-only vào data | `reader` / `reader_pwd` |

**Trạng thái ban đầu (đã dựng sẵn):**

| | Lab 1 | Lab 2 |
|---|---|---|
| User | 9 (`admin` + 8 user `zds_*`) | 4 (`admin`, `lab2_nam`, `lab2_linh`, `lab2_hung`) |
| Connection | 5 (2 MySQL + 3 Postgres) | 2 (`Lab2 - Legacy Sales`, `Lab2 - Legacy Finance`) |
| Dataset | 10 | 2 |
| Chart | 11 | 2 |
| Dashboard | 3 | 1 (`Lab2 Legacy Dashboard`) |
| Lịch sử query (SQL Lab) | 11 (10 thành công, 1 lỗi) | 3 |
| Saved query | 3 | 1 |

Tên bảng thật trong metadata: connection = `dbs`, dataset = `tables`, chart = `slices`, dashboard = `dashboards`, user = `ab_user`.

> Trình duyệt dùng chung cookie giữa các port của `localhost`. Mỗi lab đã có tên cookie riêng để không đè phiên của nhau, nhưng nếu thấy đăng nhập lạ thì hãy xoá cookie `localhost`.

## 2. Vì sao không dùng dump/restore?

`mysqldump` + restore **thay thế toàn bộ** database, không gộp được. ID trong metadata là số tự tăng và mọi bảng tham chiếu nhau bằng ID, nên khi chồng lên metadata đang có thì sẽ:
- báo trùng khoá chính, hoặc
- nếu ép ghi đè thì chart của Lab 1 trỏ nhầm vào dataset của Lab 2, owner bị đổi sai.

Vì vậy ta dùng **export/import của Superset**. Cơ chế này nhận diện object bằng UUID và tự cấp ID mới khi import:

| Loại metadata | Cách migrate |
|---|---|
| Connection + dataset | `superset export-datasources` → API `/api/v1/dataset/import/` |
| Dashboard + chart (kèm dataset, connection liên quan) | `superset export-dashboards` → API `/api/v1/dashboard/import/` |
| User (+ role gán theo **tên role**) | Script `fake_data/sync_users.py` (Superset không có lệnh export user) |
| **Lịch sử query** (SQL Lab) và **saved query** | Không có lệnh export. Script `fake_data/sync_query_history.py` copy từng dòng, đổi ID theo `username` và tên connection |
| Role tự tạo + permission (nếu Lab 1 có) | `superset fab export-roles` / `import-roles` |

Import bằng REST API thay vì lệnh `superset import-dashboards`, vì file export **không chứa mật khẩu connection**, còn lệnh CLI không cho truyền mật khẩu nên bị từ chối ở bước validate. API có tham số `passwords` để làm việc này.

## 3. Dựng môi trường (nếu chưa có)

```bash
docker compose up -d --build        # lần đầu build image ~2-3 phút
docker compose ps                   # chờ cả 5 container "healthy"

docker exec superset_lab1 python /app/fake_data/seed_fake_metadata.py     # metadata cho Lab 1
docker exec superset_lab2 python /app/fake_data/seed_lab2_existing.py     # metadata riêng của Lab 2

# Lịch sử query thật: chạy query qua SQL Lab bằng API (nhiều user) để bảng query / saved_query có dữ liệu
docker exec superset_lab1 python /app/fake_data/seed_query_history.py
docker exec superset_lab2 python /app/fake_data/seed_query_history.py lab2
```

## 4. Các bước merge (làm tay)

Chạy từ thư mục gốc của project. Muốn chạy tự động toàn bộ thì dùng `./scripts/merge_lab1_to_lab2.sh`. Lab 2 (5.0.0) sẽ tự nâng schema khi khởi động; với import, không cần dump/restore giữa hai version.
**Lab 2 không cần dừng** trong suốt quá trình này.

### Bước 0: Xem trạng thái trước khi merge

```bash
docker exec postgres_lab2 psql -U superset -d superset_meta -c "
  SELECT 'users', COUNT(*) FROM ab_user UNION ALL SELECT 'connections', COUNT(*) FROM dbs
  UNION ALL SELECT 'datasets', COUNT(*) FROM tables UNION ALL SELECT 'charts', COUNT(*) FROM slices
  UNION ALL SELECT 'dashboards', COUNT(*) FROM dashboards;"
```

Kết quả phải là `4, 2, 2, 2, 1`. Đếm thêm lịch sử: `SELECT COUNT(*) FROM query` (3) và `SELECT COUNT(*) FROM saved_query` (1). Mở http://localhost:8089 đăng nhập `admin` / `admin` để xem tận mắt.

### Bước 1: Backup Lab 2 (bước quan trọng nhất)

Vì đang ghi vào một hệ thống có dữ liệu thật, hãy backup trước để có thể quay lại:

```bash
docker exec postgres_lab2 sh -c \
  "pg_dump -U postgres --no-owner superset_meta > /backup/lab2_before_merge.sql"

# lưu danh sách những gì Lab 2 đang có, để bước kiểm tra biết cái gì "không được mất"
docker exec superset_lab2 python /app/fake_data/verify_merge.py snapshot 2>/dev/null > backup/lab2_before.json
```

Thư mục `./backup` trên máy được mount vào `/backup` trong `mysql_lab1` và `postgres_lab2`.

### Bước 2: Export từ Lab 1

```bash
docker exec superset_lab1 superset export-datasources -f /tmp/datasources.zip
docker exec superset_lab1 superset export-dashboards  -f /tmp/dashboards.zip

docker cp superset_lab1:/tmp/datasources.zip backup/
docker cp superset_lab1:/tmp/dashboards.zip  backup/
unzip -l backup/dashboards.zip        # xem bên trong: databases/, datasets/, charts/, dashboards/ dạng YAML
```

### Bước 2b: Role tự tạo (nếu có), làm TRƯỚC Bước 3

`sync_users.py` gán role theo **tên** và **không tạo role**: role chưa có ở Lab 2 thì user vẫn được thêm nhưng **thiếu role đó** (`WARN`). Vì vậy role tự tạo phải có ở Lab 2 **trước** Bước 3. Bỏ qua bước này nếu Lab 1 chỉ dùng role mặc định (Admin, Alpha, Gamma, Public, sql_lab; Superset 2.1.1 còn có `granter`).

```bash
docker exec superset_lab1 superset fab export-roles --path /tmp/roles.json
docker cp superset_lab1:/tmp/roles.json - | docker cp - superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/roles.json
```

**Lọc file trước khi import** (chỉ giữ role tự tạo, bỏ quyền có ID cũ):

```bash
docker exec -i superset_lab2 python - <<'EOF'
import json
BUILTIN = {"Admin", "Alpha", "Gamma", "Public", "sql_lab", "granter"}   # role mặc định của Superset
roles = json.load(open("/tmp/roles.json"))
custom, dropped = [], 0
for r in roles:
    if r["name"] in BUILTIN:
        continue
    keep = [p for p in r["permissions"] if "(id:" not in p["view_menu"]["name"]]   # quyền chứa ID cũ sẽ trỏ sai
    dropped += len(r["permissions"]) - len(keep)
    custom.append({**r, "permissions": keep})
json.dump(custom, open("/tmp/roles_custom.json", "w"), indent=1)
print(f"giữ {len(custom)} role tự tạo: {[r['name'] for r in custom]}; bỏ {dropped} quyền chứa ID")
EOF
docker exec superset_lab2 superset fab import-roles --path /tmp/roles_custom.json
```

**Vì sao phải lọc (đã thử ở lab):**
- Import **nguyên file** cộng thêm quyền cũ của 2.x vào **role mặc định** của Lab 2: Gamma từ 74 lên 117 (+43 quyền, ví dụ `can_add_slices on Superset`, `can_copy_dash on Superset`), Admin 161 → 228, Alpha 99 → 146, sql_lab 25 → 30. Đó là quyền 5.0.0 đã bỏ hoặc đổi tên, nên role mặc định bị **phình quyền**.
- Import file **đã lọc**: chỉ tạo role tự tạo, role mặc định **giữ nguyên** (Admin 161, Alpha 99, Gamma 74, sql_lab 25).

**Giới hạn:** lệnh này chỉ chuyển được quyền **không chứa ID** (ví dụ `can_read on Dashboard`). Quyền vào từng dataset/database (`[db].[table](id:N)`) bị lệch ID (xem `docs/MIGRATION_GUIDE.md` bẫy #18). Dataset chỉ tồn tại ở Lab 2 sau Bước 4, nên các quyền này phải được **cấp lại sau Bước 4 và Bước 7 (`superset init`)**, bằng tay hoặc script (chưa có). Kiểm tra role đã có: `SELECT name FROM ab_role;` trên metadata Lab 2. Nếu Lab 1 đã **tự thêm quyền vào role mặc định** (ví dụ vào Gamma), phần đó cũng không tự chuyển: so sánh và bổ sung tay.

### Bước 3: Thêm user của Lab 1 vào Lab 2

```bash
docker exec superset_lab2 python /app/fake_data/sync_users.py
```

Kết quả mong đợi: `added 8` (các user `zds_*`) và `skipped 1` (`admin` đã có nên giữ nguyên bản của Lab 2).
- User khớp theo `username`. User đã có ở Lab 2 không bị sửa gì.
- Giữ nguyên mật khẩu (hash) của Lab 1, nên `zds_alice` đăng nhập được ngay ở Lab 2.
- Role được gán theo **tên** role (`Alpha`, `Gamma`...), không theo ID. Nếu role chưa có ở Lab 2 thì script in cảnh báo.

### Bước 4: Import connection, dataset, chart, dashboard vào Lab 2

File export **không chứa mật khẩu connection**, nên phải cung cấp lúc import. Nếu có nhiều connection (ở hệ thống thật có thể hàng chục), đừng gõ tay: mật khẩu đang nằm trong metadata của Lab 1 (dạng mã hoá), để Superset giải mã và xuất ra file.

```bash
# 4a. Xuất mật khẩu của mọi connection ở Lab 1 ra file JSON {"tên connection": "mật khẩu"}
docker exec superset_lab1 python /app/fake_data/export_db_passwords.py /tmp/passwords.json

# 4b. Chuyển thẳng từ Lab 1 sang Lab 2 (không đi qua máy bạn) và cho Lab 2 quyền đọc
docker cp superset_lab1:/tmp/passwords.json - | docker cp - superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/passwords.json

# 4c. Import, mỗi connection lấy đúng mật khẩu của nó trong file
docker cp fake_data/import_bundle_direct.py superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/import_bundle_direct.py
docker cp backup/datasources.zip     superset_lab2:/tmp/
docker cp backup/dashboards.zip      superset_lab2:/tmp/
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json superset_lab2 python /tmp/import_bundle_direct.py dataset   /tmp/datasources.zip admin
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json superset_lab2 python /tmp/import_bundle_direct.py dashboard /tmp/dashboards.zip admin

# 4d. XOÁ file mật khẩu ngay (nó là mật khẩu dạng chữ thường)
docker exec superset_lab1 rm -f /tmp/passwords.json
docker exec superset_lab2 rm -f /tmp/passwords.json
```

Mỗi lệnh import phải in `... import (direct): OK, N connection(s) in bundle`. Script chạy Superset import **ngay trong container** (không đăng nhập, không HTTP); tham số cuối (`admin`) là user đã tồn tại làm owner.
- **Chọn mật khẩu cho từng connection**, theo thứ tự: file `DB_PASSWORDS_FILE` → biến `DB_PASSWORDS_JSON` (cùng dạng, gõ trực tiếp) → biến `DB_PASSWORD` (dùng cho mọi connection không có trong hai nguồn trên, mặc định `reader_pwd`). Connection nào không có trong danh sách sẽ in dòng `note: no specific password...`.
- **Mật khẩu sai thì import bị từ chối**, không lưu âm thầm: Superset 5.0.0 kết nối thử tới database khi nạp dataset, nên sẽ báo `password authentication failed` (HTTP 500). Đã thử thật.
- Nếu không muốn (hoặc không được phép) lấy mật khẩu từ Lab 1, tự lập file JSON từ kho mật khẩu của công ty, cùng dạng trên.
- Lỗi `Permission denied` khi đọc file: `docker cp` giữ quyền `600` của người tạo, nên phải chạy `chown superset` như 4b.
- Object của Lab 1 được **thêm mới** vào Lab 2 với ID mới. Object cũ của Lab 2 không bị xoá hay sửa. Object đã từng import (cùng UUID) bị ghi đè bằng bản của Lab 1, nên chạy lại không tạo trùng.
- **Bảo mật:** file mật khẩu là chữ thường. Không commit vào git, không để lại trên máy, xoá ngay sau khi import (4d). `./scripts/merge_lab1_to_lab2.sh` tự làm 4a-4d và xoá file.

### Bước 5: Khôi phục trạng thái xuất bản của dashboard

```bash
docker exec superset_lab2 python /app/fake_data/sync_dashboard_published.py
```

Kết quả mong đợi: `dashboards: 3 updated`.
- **Vì sao cần bước này:** file export của Superset **2.1.x không chứa** trường `published`. Khi nạp vào 5.0.0, cả 3 dashboard bị mặc định thành **chưa xuất bản**. Admin vẫn thấy hết, nhưng user thường (Alpha, Gamma...) chỉ thấy dashboard đã xuất bản hoặc do mình sở hữu, nên `zds_alice` chỉ thấy 1 trong 4 dashboard.
- Script khớp dashboard theo UUID và chép lại cờ `published` từ Lab 1. Dashboard riêng của Lab 2 không bị đụng.
- Bước này phát hiện ra nhờ thử thật trên hai version khác nhau, nên khi làm với hệ thống thật hãy kiểm tra thêm các trường khác có bị mất không (xem mục 7).

### Bước 6: Copy lịch sử query và saved query

```bash
docker exec superset_lab2 python /app/fake_data/sync_query_history.py
```

Kết quả mong đợi: `query added 11` và `saved_query added 3`.
- **Phải chạy sau Bước 4** (import connection), vì script gán dòng lịch sử vào connection theo **tên** connection (ví dụ `MySQL - Sales`), nên connection phải đã tồn tại ở Lab 2. Dòng nào có connection không tồn tại ở Lab 2 sẽ bị bỏ qua và in cảnh báo.
- Người chạy query được gán lại theo `username`, nên phải chạy sau Bước 3 (thêm user).
- Dòng đã có (khớp `client_id` với query, khớp `uuid` với saved query) thì bỏ qua, nên chạy lại không tạo trùng. Lịch sử cũ của Lab 2 không bị đụng.
- Giữ nguyên thời điểm chạy gốc. **Không mang theo kết quả đã cache** của từng query: danh sách lịch sử và câu SQL vẫn còn, còn số liệu trả về thì phải chạy lại query.
- Tab đang mở trong SQL Lab (`tab_state`) không được copy.

### Bước 7: `db upgrade`, `init`, restart Lab 2

```bash
docker exec superset_lab2 superset db upgrade   # đưa schema lên version của Superset; no-op nếu cùng version
docker exec superset_lab2 superset init         # sync role/permission cho connection và dataset mới
docker compose restart superset_lab2
docker compose ps superset_lab2                 # chờ "healthy"
```

### Bước 8: Kiểm chứng

```bash
./scripts/verify.sh
```

Script kiểm tra 3 việc:
1. Mọi thứ của Lab 1 (kể cả trạng thái dashboard, lịch sử query và saved query) đã có trong Lab 2, và **không thứ gì của Lab 2 bị mất** so với bản snapshot ở Bước 1.
2. Cả 7 connection decrypt được mật khẩu và mở kết nối được.
3. Cả 13 chart chạy ra dữ liệu và `zds_alice` (user Alpha được migrate) thấy đủ 4 dashboard. Đồng thời `lab2_nam` (user cũ của Lab 2) vẫn đăng nhập được.

Kết quả mong đợi: `MERGE OK` và `ALL CHECKS PASSED`.

Xem bằng mắt tại http://localhost:8089: sẽ thấy 4 dashboard (1 cũ + 3 mới), 7 connection, 12 user. Vào SQL Lab → Query History thấy 14 dòng (3 cũ của Lab 2 + 11 từ Lab 1). Thử đăng nhập bằng `zds_alice` / `Passw0rd!` và `lab2_nam` / `Lab2Passw0rd!`.



## 5. Rollback

Nếu merge làm hỏng Lab 2, khôi phục về bản backup ở Bước 1:

```bash
docker compose stop superset_lab2
docker exec postgres_lab2 dropdb -U postgres superset_meta
docker exec postgres_lab2 createdb -U postgres -O superset superset_meta
docker exec postgres_lab2 sh -c "psql -U postgres -d superset_meta -f /backup/lab2_before_merge.sql"
docker compose start superset_lab2
```

## 6. Reset để làm lại

```bash
# Đưa Lab 2 về trạng thái ban đầu (chỉ có dữ liệu riêng của nó); Lab 1 giữ nguyên
./scripts/reset_lab2.sh

# Xoá sạch mọi thứ, dựng lại từ đầu
docker compose down -v
docker compose up -d --build
docker exec superset_lab1 python /app/fake_data/seed_fake_metadata.py
docker exec superset_lab1 python /app/fake_data/seed_query_history.py
docker exec superset_lab2 python /app/fake_data/seed_lab2_existing.py
docker exec superset_lab2 python /app/fake_data/seed_query_history.py lab2
```

## 7. Những điểm dễ sai và giới hạn

1. **`SECRET_KEY` giữa 2 service (ZDS Lab1,2) là 2 key khác nhau, mục đích chính dùng để hash 2 chiều mật kiệu kết nối database --> export password db connection từ ZDS Lab1(export_db_passwords.py) sẽ tự giải mã ra plaintext --> khi import vào ZDS Lab2 thì sẽ mã hoá chúng lại theo secret key của ZDS Lab2 (import_bundle_direct.py)
2. **Owner không được giữ nguyên.** Object import vào đều thuộc user chạy import (`admin`). Hệ quả: user Alpha **không sửa được** dashboard của chính mình. Muốn giữ owner gốc cần thêm bước map owner theo `username` (chưa có script).
3. **Trùng tên connection nhưng khác UUID** thì import báo lỗi. Đổi tên một bên trước khi import.
4. **Lịch sử query chỉ mang được phần "nhật ký"** (ai chạy, SQL gì, lúc nào, thành công hay lỗi), không mang kết quả đã cache. **Không mang theo:** tab SQL Lab đang mở, log, alert/report.
5. **Version Superset:** chỉ import từ version cũ sang version mới hơn hoặc bằng.
6. **Export từ Superset cũ có thể thiếu trường** mà bản mới có. Đã gặp: 2.1.1 không xuất `published` của dashboard (đã xử lý ở Bước 5). Khi làm thật, so sánh vài dashboard, dataset, chart quan trọng giữa hai bên sau khi nạp để tìm trường bị mất.
7. **Hành vi SQL Lab khác nhau giữa các version.** Ví dụ Superset 2.1.1 không tự áp schema cho Postgres, nên query phải ghi `dw.fact_revenue` thay vì `fact_revenue`. Lịch sử đã copy chỉ là nhật ký; chạy lại query cũ trên 5.0.0 có thể khác kết quả.
8. Superset MySQL có thể in warning `Cannot drop column 'druid_datasource_id'` khi `db upgrade`. Đây là warning đã biết, bỏ qua được.
9. **Lab 1 (MySQL) và Lab 2 (Postgres) biểu diễn `uuid` và `boolean` khác nhau** — đã gặp thật khi build lab này: cột `uuid` là `BINARY(16)` (bytes) trên MySQL nhưng kiểu `UUID` gốc (chuỗi) trên Postgres, nên so sánh trực tiếp giá trị đọc từ hai bên luôn sai (`sync_dashboard_published.py`, `sync_query_history.py` phải tự chuẩn hoá về `str(uuid)` trước khi so khớp). Tương tự, `COALESCE(published, 0)` báo lỗi kiểu trên Postgres (`boolean` không tự ép sang `integer`); và cột `sql` của `saved_query` cần backtick trên MySQL (từ khoá dành riêng) nhưng backtick lại là cú pháp sai trên Postgres (`verify_merge.py` tự chọn ký tự quote theo dialect). Khi tự viết thêm script copy dòng giữa hai lab, luôn kiểm tra lại các điểm này.

## 8. Cấu trúc thư mục

```
docker-compose.yml               5 container: 2 Superset, mysql_lab1, postgres_lab1, postgres_lab2
docker/Dockerfile                apache/superset:<version> + psycopg2 + mysqlclient (tự nhận biết 2.x dùng Python hệ thống, 5.x dùng venv)
superset/superset_config.py      đọc META_DB_URI, SUPERSET_SECRET_KEY từ env; cookie riêng mỗi lab
superset/bootstrap.sh            db upgrade -> create-admin -> init -> gunicorn
initdb/mysql/00_superset_meta.sql        tạo DB metadata (MySQL) + user superset, cho mysql_lab1
initdb/mysql/10_lab1_data.sql             data thật sales, crm (chỉ mysql_lab1)
initdb/postgres/00_superset_meta_lab2.sql tạo DB metadata (Postgres) + user superset, cho postgres_lab2
initdb/postgres/10_lab1_data.sql         data thật finance, warehouse, marketing (postgres_lab1)
fake_data/seed_fake_metadata.py     seed metadata cho Lab 1
fake_data/seed_lab2_existing.py     seed metadata "có sẵn" cho Lab 2
fake_data/sync_users.py             thêm user Lab 1 vào Lab 2 (khớp theo username)
fake_data/sync_dashboard_published.py  chép cờ published của dashboard (2.1.1 không xuất trường này)
fake_data/seed_query_history.py     tạo lịch sử query + saved query thật bằng cách chạy qua SQL Lab API
fake_data/sync_query_history.py     copy lịch sử query + saved query Lab 1 -> Lab 2
fake_data/export_db_passwords.py    xuất mật khẩu mọi connection ra JSON (Superset tự giải mã)
fake_data/verify_merge.py           snapshot + so sánh tên object Lab 1 vs Lab 2
fake_data/check_connections.py      test kết nối từng connection
fake_data/smoke_test_api.py         login qua API + chạy query mọi chart
scripts/merge_lab1_to_lab2.sh       toàn bộ Bước 1 -> 7 tự động
scripts/reset_lab2.sh               đưa Lab 2 về trạng thái trước merge
scripts/verify.sh                   Bước 8
backup/                             nơi chứa file backup / export
```
