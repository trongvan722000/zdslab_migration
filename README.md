# ZDS Lab: merge metadata Superset Lab 1 vào Lab 2

Chuyển **metadata** Superset (connection, dataset, chart, dashboard, user, role tự tạo, lịch sử query SQL Lab, saved query) từ Lab 1 sang Lab 2 theo kiểu **thêm vào**: những gì Lab 2 đang có vẫn giữ nguyên. Data thật không di chuyển, cả hai lab cùng truy vấn vào các data server đó.

| Tài liệu | Dùng khi |
|---|---|
| README này | Dựng lab, chạy thử toàn bộ quy trình bằng data giả |
| [docs/PRODUCTION_RUNBOOK.md](docs/PRODUCTION_RUNBOOK.md) | Migrate thật |
| [docs/REHEARSAL_VM_CONDA.md](docs/REHEARSAL_VM_CONDA.md) | Diễn tập với dump/backup thật (Superset chạy conda trên VM) |
| [docs/MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md) | Lý thuyết, các bẫy đã gặp |
| [docs/EXECUTION_HANDOFF.md](docs/EXECUTION_HANDOFF.md) | Bàn giao cho người chạy |

## 1. Kiến trúc

| Container | Vai trò | Truy cập |
|---|---|---|
| `superset_lab1` | Superset nguồn **2.1.1**, metadata ở `mysql_lab1` | http://localhost:8088 |
| `superset_lab2` | Superset đích **5.0.0**, metadata ở `postgres_lab2` | http://localhost:8089 |
| `mysql_lab1` | **MariaDB 10.3.32**: metadata Lab 1 (`superset_meta`) + data `sales`, `crm` | localhost:3307 |
| `postgres_lab1` | Postgres 15: data `finance`, `warehouse`, `marketing` | localhost:5433 |
| `postgres_lab2` | Postgres 15: metadata Lab 2 (`superset_meta`) | localhost:5434 |

Lab mô phỏng đúng môi trường thật ở ba điểm:
- **Khác version** (2.1.1 → 5.0.0): schema metadata khác nhau, nên không dump/restore giữa hai lab được, phải export/import.
- **Khác engine metadata**: Lab 1 là MariaDB (dùng URI `mysql://`, nhưng không phải MySQL 8: dump thật có bảng `SEQUENCE` mà MySQL 8 không đọc được), Lab 2 là Postgres. Các script copy dòng phải tự xử lý khác biệt `uuid` / `boolean` / dấu quote giữa hai bên.
- **Khác `SECRET_KEY`**: mật khẩu connection được giải mã bằng key Lab 1 rồi mã hoá lại bằng key Lab 2, hai key không cần giống nhau.

Mọi cấu hình (SECRET_KEY, version, image, port) nằm trong [.env.example](.env.example). Thiếu `SUPERSET_SECRET_KEY_LAB1/LAB2` thì `docker compose up` dừng ngay, có chủ đích. Image 2.1.1 chỉ có bản amd64, nên trên Apple Silicon `superset_lab1` chạy giả lập và khởi động chậm.

Tài khoản trong lab:

| | user / password |
|---|---|
| Admin (cả 2 lab) | `admin` / `admin` |
| User Lab 1 | `zds_alice`, `zds_frank` (Alpha), `zds_bob`, `zds_carol`, `zds_emma`, `zds_grace` (Gamma), `zds_david` (sql_lab), `zds_henry` (Admin), mật khẩu `Passw0rd!` |
| User có sẵn của Lab 2 | `lab2_nam` (Alpha), `lab2_linh` (Gamma), `lab2_hung` (Admin), mật khẩu `Lab2Passw0rd!` |
| MariaDB root / Postgres superuser | `root` / `root`, `postgres` / `postgres` |
| Metadata DB | `superset` / `superset` |
| Read-only vào data | `reader` / `reader_pwd` |

Trạng thái ban đầu sau khi seed:

| | Lab 1 | Lab 2 |
|---|---|---|
| User | 9 | 4 |
| Connection | 5 | 2 |
| Dataset | 10 | 2 |
| Chart | 11 | 2 |
| Dashboard | 3 | 1 |
| Lịch sử query | 11 | 3 |
| Saved query | 3 | 1 |

Tên bảng trong metadata: connection = `dbs`, dataset = `tables`, chart = `slices`, dashboard = `dashboards`, user = `ab_user`.

## 2. Cách migrate từng loại metadata

Dump/restore **thay toàn bộ** database chứ không gộp được. ID là số tự tăng và mọi bảng tham chiếu nhau bằng ID, nên ghi chồng lên Lab 2 sẽ trùng khoá hoặc trỏ nhầm object. Vì vậy:

| Loại | Export (Lab 1) | Import (Lab 2) |
|---|---|---|
| **Mọi connection** (43 ở prod) | `sync/export_databases.py` → `databases.zip` | `sync/import_bundle_direct.py database` |
| Dataset (+ connection mà dataset dùng) | `sync/export_bundle.py dataset` → `datasources.zip` | `sync/import_bundle_direct.py dataset` |
| Dashboard + chart (+ dataset, connection liên quan) | `sync/export_bundle.py dashboard` → `dashboards.zip` | `sync/import_bundle_direct.py dashboard` |
| Mật khẩu connection | `sync/export_db_passwords.py` → `passwords.json` | truyền vào lúc import |
| Role tự tạo | `superset fab export-roles` | `sync/filter_roles.py` rồi `superset fab import-roles` |
| User | không có lệnh export | `sync/sync_users.py` (khớp theo `username`) |
| Cờ `published` của dashboard | 2.1.1 không export trường này | `sync/sync_dashboard_published.py` (khớp theo UUID) |
| Lịch sử query, saved query | không có lệnh export | `sync/sync_query_history.py` (copy dòng) |

Ba file ZIP **bổ sung cho nhau, không thay thế nhau**:
- `datasources.zip` chỉ chứa connection có dataset dùng tới. Ở prod là 20/43, phần còn lại (chỉ dùng trong SQL Lab, hoặc chưa dùng) chỉ có trong `databases.zip`.
- `databases.zip` chỉ chứa connection, không có dataset.
- Object trùng UUID được ghi đè khi import, nên phần chồng giữa các file không tạo bản trùng.

Vì sao dùng script thay cho lệnh CLI có sẵn:
- **Export:** lệnh `superset export-datasources` / `export-dashboards` của 2.1.1 ghi cứng user `admin`. Metadata thật không có user này nên lệnh lỗi `'NoneType' object has no attribute 'is_anonymous'`. `export_bundle.py` chạy đúng lệnh export đó nhưng cho chọn user (cần role Admin, không cần mật khẩu) và chỉ đọc. Ở lab có sẵn `admin` nên lệnh CLI cũ vẫn chạy được.
- **Import:** file export không chứa mật khẩu connection. Lệnh `superset import-*` không cho truyền mật khẩu, còn API thì cần đăng nhập (prod là LDAP + OTP). `import_bundle_direct.py` chạy import ngay trong tiến trình Superset: không cần đăng nhập, không bị timeout HTTP, và nhận mật khẩu từ file.

Thư mục `sync/` được mount vào cả hai container tại `/app/sync` (chỉ đọc), nên không cần `docker cp` script.

## 3. Dựng lab

```bash
cp .env.example .env && chmod 600 .env   # .env không được commit
docker compose up -d --build              # lần đầu build ~2-3 phút
docker compose ps                         # chờ 5 container "healthy"

docker exec superset_lab1 python /app/fake_data/seed_fake_metadata.py
docker exec superset_lab2 python /app/fake_data/seed_lab2_existing.py
docker exec superset_lab1 python /app/fake_data/seed_query_history.py
docker exec superset_lab2 python /app/fake_data/seed_query_history.py lab2
```

Lần đầu khởi động với volume trống, `mysql_lab1` / `postgres_lab*` chạy các file trong `initdb/` để tạo DB và user. **Các file này chỉ chạy một lần.** Sửa chúng rồi `up` lại sẽ không có tác dụng: phải xoá volume (`docker compose down -v`). Nếu một câu SQL init lỗi, container dừng giữa chừng, và lần restart sau sẽ bỏ qua init. Khi đó xem `docker logs mysql_lab1` của lần chạy đầu và xoá volume.

## 4. Các bước merge

Chạy từ thư mục gốc. Lab 2 không cần dừng cho tới Bước 7. Nên ghi log mọi lệnh (`2>&1 | tee <tên>_$(date +%H%M).log`).

Khai báo một lần trong shell trước khi chạy các bước (đây là **tên user**, không cần mật khẩu):

```bash
ADMIN_LAB1=admin   # user có role Admin ở Lab 1: export thấy hết mọi object. Prod: username thật, không phải "admin"
ADMIN_LAB2=admin   # user có sẵn ở Lab 2: làm owner của object được import
```

### Bước 0: Trạng thái trước merge

```bash
docker exec postgres_lab2 psql -U superset -d superset_meta -c "
  SELECT 'users', COUNT(*) FROM ab_user UNION ALL SELECT 'connections', COUNT(*) FROM dbs
  UNION ALL SELECT 'datasets', COUNT(*) FROM tables UNION ALL SELECT 'charts', COUNT(*) FROM slices
  UNION ALL SELECT 'dashboards', COUNT(*) FROM dashboards
  UNION ALL SELECT 'query', COUNT(*) FROM query UNION ALL SELECT 'saved_query', COUNT(*) FROM saved_query;"
```

Lab mong đợi: `4, 2, 2, 2, 1, 3, 1`.

### Bước 1: Backup Lab 2

```bash
docker exec postgres_lab2 sh -c "pg_dump -U postgres --no-owner superset_meta > /backup/lab2_before_merge.sql"
docker exec superset_lab2 python /app/sync/verify_merge.py snapshot 2>/dev/null > backup/lab2_before.json
```

`./backup` được mount vào `/backup` trong `mysql_lab1` và `postgres_lab2`. Snapshot dùng ở Bước 8 để chứng minh không mất gì của Lab 2.

### Bước 2: Export từ Lab 1

```bash
docker exec superset_lab1 python /app/sync/export_databases.py /tmp/databases.zip "$ADMIN_LAB1" 2>&1 | grep -E "^export|Error"
docker exec superset_lab1 python /app/sync/export_bundle.py dataset   /tmp/datasources.zip "$ADMIN_LAB1" 2>&1 | grep -E "^export|Error"
docker exec superset_lab1 python /app/sync/export_bundle.py dashboard /tmp/dashboards.zip  "$ADMIN_LAB1" 2>&1 | grep -E "^export|Error"
docker exec superset_lab1 python /app/sync/export_db_passwords.py /tmp/passwords.json 2>&1 | grep '^wrote'

for f in databases datasources dashboards passwords; do
  ext=$([ $f = passwords ] && echo json || echo zip)
  docker cp superset_lab1:/tmp/$f.$ext - | docker cp - superset_lab2:/tmp/
done
docker exec -u root superset_lab2 chown superset /tmp/databases.zip /tmp/datasources.zip /tmp/dashboards.zip /tmp/passwords.json
```

- `export_bundle.py` chạy đúng `ExportDatasetsCommand` / `ExportDashboardsCommand` mà lệnh CLI dùng, chỉ khác là cho chọn user. **Nếu Lab 1 có user `admin`** (lab giả có), lệnh CLI gốc cho ra ZIP tương đương, dùng được để thay hoặc đối chiếu:
  ```bash
  docker exec superset_lab1 superset export-datasources -f /tmp/datasources.zip
  docker exec superset_lab1 superset export-dashboards  -f /tmp/dashboards.zip
  ```
  Metadata thật không có `admin`: lệnh CLI lỗi `'NoneType' object has no attribute 'is_anonymous'`, phải dùng `export_bundle.py`.
- Mỗi lệnh export kết thúc bằng `export: wrote ...: N of M ...`. Nếu N khác M, script báo lỗi: user đó không thấy hết, hãy chọn user có role Admin.
- `export_databases.py` in hai nhóm connection, có và không có dataset. Nhóm "không có" chính là phần `datasources.zip` thiếu.
- `export_db_passwords.py` in số connection **không có mật khẩu lưu sẵn**. Nếu số này lớn hơn 0, lúc import phải thêm `-e DB_PASSWORD=''` (hoặc mật khẩu đúng), nếu không import sẽ dừng với `ABORTED, no password for ...`.
- `docker cp ... - | docker cp - ...` chuyển thẳng từ Lab 1 sang Lab 2, file mật khẩu không nằm lại trên máy. `chown` cần thiết vì `docker cp` giữ quyền `600` của người tạo.

### Bước 3: Role tự tạo (nếu có), làm trước Bước 4

`sync_users.py` gán role theo **tên** và không tạo role. Role tự tạo phải có ở Lab 2 trước, nếu không user được thêm nhưng thiếu role (`WARN`). Bỏ qua bước này nếu Lab 1 chỉ dùng role mặc định.

```bash
docker exec superset_lab1 superset fab export-roles --path /tmp/roles.json
docker cp superset_lab1:/tmp/roles.json - | docker cp - superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/roles.json
docker exec superset_lab2 python /app/sync/filter_roles.py /tmp/roles.json /tmp/roles_custom.json
docker exec superset_lab2 superset fab import-roles --path /tmp/roles_custom.json
```

`filter_roles.py` chỉ giữ role tự tạo và bỏ quyền chứa ID cũ (`[db].[table](id:N)`). Import nguyên file sẽ làm role mặc định của Lab 2 phình quyền: đã đo ở lab, Gamma tăng từ 74 lên 117 quyền. Quyền theo từng dataset/database phải cấp lại sau Bước 7, hiện chưa có script.

### Bước 4: Thêm user

```bash
docker exec superset_lab2 python /app/sync/sync_users.py
```

Lab mong đợi: `added 8`, `skipped 1` (`admin` đã có). Giữ nguyên hash mật khẩu và gán role theo tên. User đã có ở Lab 2 không bị sửa.

### Bước 5: Import connection, dataset, dashboard

Phải đúng thứ tự **database → dataset → dashboard**:

```bash
for spec in database:databases dataset:datasources dashboard:dashboards; do
  docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json superset_lab2 \
    python /app/sync/import_bundle_direct.py ${spec%%:*} /tmp/${spec#*:}.zip "$ADMIN_LAB2" || break
done

# Xoá file mật khẩu ngay (mật khẩu dạng chữ thường)
docker exec superset_lab1 rm -f /tmp/passwords.json
docker exec superset_lab2 rm -f /tmp/passwords.json
```

- Mỗi lần import phải in `... import (direct): OK, N connection(s) in bundle`, không có dòng `note:` và không có `ABORTED`.
- `$ADMIN_LAB2` là user **của Lab 2** sẽ làm owner. User đó phải có sẵn ở Lab 2.
- Mật khẩu lấy theo tên connection: `DB_PASSWORDS_FILE` → `DB_PASSWORDS_JSON` → `DB_PASSWORD`. Không tìm được mật khẩu thì script dừng **trước khi ghi**. Import lại **không** sửa được mật khẩu đã lưu sai.
- Log có `Couldn't check if table ... exists` / `Error processing catalog 'None'` là do Lab 2 chưa kết nối được data server (IP chưa được cấp quyền). Dataset vẫn được import.

### Bước 6: Cờ published, lịch sử query, saved query

```bash
docker exec superset_lab2 python /app/sync/sync_dashboard_published.py   # lab: dashboards: 3 updated
docker exec superset_lab2 python /app/sync/sync_query_history.py         # lab: query added 11, saved_query added 3
```

- **Bắt buộc chạy sau Bước 4 và Bước 5.** Lịch sử query gán lại user theo `username` và connection theo **tên**.
- Nếu chạy trước khi import `databases.zip`, saved query của connection chưa có ở Lab 2 sẽ bị **gán `db_id = NULL` mà không báo**. Chạy sync lại cũng không sửa được, vì dòng đã có (cùng uuid) sẽ bị bỏ qua. Query history của connection chưa có thì bị bỏ qua kèm `WARN`.
- Không mang theo kết quả đã cache, tab SQL Lab đang mở, log, alert/report.

### Bước 7: `db upgrade`, `init`, restart Lab 2

```bash
docker exec superset_lab2 superset db upgrade   # no-op nếu schema đã ở head
docker exec superset_lab2 superset init
docker compose restart superset_lab2
```

### Bước 8: Kiểm chứng

```bash
./scripts/verify.sh                                                     # lab: MERGE OK, ALL CHECKS PASSED
docker exec superset_lab2 python /app/sync/check_connections.py        # từng connection: connect OK / FAIL

# So từng saved query giữa hai lab bằng EXPLAIN (không đọc data, không ghi gì)
docker exec superset_lab1 python /app/sync/check_queries.py saved --report /tmp/rep_lab1.json > /dev/null 2>&1
docker cp superset_lab1:/tmp/rep_lab1.json - | docker cp - superset_lab2:/tmp/
docker exec superset_lab2 python /app/sync/check_queries.py saved --full-sql --compare /tmp/rep_lab1.json 2>&1 | grep '^check'
```

- `verify_merge.py check` (trong `verify.sh`) báo lỗi nếu mất gì của Lab 2 hoặc thiếu gì của Lab 1.
- `check_queries.py`: dòng `REGR` (OK ở Lab 1, FAIL ở Lab 2) mới là lỗi migrate. FAIL ở cả hai lab là lỗi sẵn có trong SQL. `CONN` nghĩa là không kết nối được, xem lại `check_connections.py`. Thay `saved` bằng `history 100` để kiểm lịch sử query.
- Lab mong đợi trên http://localhost:8089: 4 dashboard, 7 connection, 12 user, 14 dòng Query History. Đăng nhập thử `zds_alice` / `Passw0rd!` và `lab2_nam` / `Lab2Passw0rd!`.

## 5. Rollback

```bash
docker compose stop superset_lab2
docker exec postgres_lab2 dropdb -U postgres superset_meta
docker exec postgres_lab2 createdb -U postgres -O superset superset_meta
docker exec postgres_lab2 psql -U superset -d superset_meta -f /backup/lab2_before_merge.sql
docker compose start superset_lab2
```

**Restore bằng user owner (`-U superset`), không dùng `postgres`.** Dump tạo với `--no-owner`, nên bảng thuộc về user chạy restore. Restore bằng `postgres` thì Superset lỗi `permission denied for table ab_role` và restart liên tục.

## 6. Reset để làm lại

```bash
./scripts/reset_lab2.sh        # Lab 2 về trạng thái ban đầu, Lab 1 giữ nguyên (XOÁ cả backup/: đừng chạy khi có backup thật)

docker compose down -v         # xoá sạch, dựng lại như mục 3
```

## 7. Lỗi thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `export-datasources` lỗi `'NoneType' object has no attribute 'is_anonymous'` | 2.1.1 ghi cứng user `admin`, metadata thật không có | `sync/export_bundle.py` với user có role Admin |
| Lab 2 chỉ có 20/43 connection | `datasources.zip` chỉ chứa connection có dataset | Thêm `export_databases.py` + `import_bundle_direct.py database` |
| `check_queries.py` báo `FAIL <db_id None missing>` | `saved_query.db_id` NULL: mồ côi sẵn ở Lab 1, hoặc sync chạy trước khi đủ connection | So với Lab 1 bằng `--compare`; luôn import `databases.zip` trước Bước 6 |
| Import báo `ABORTED, no password for ...` | Connection không có trong `passwords.json` | Thêm vào file, hoặc `-e DB_PASSWORD=...` |
| `No module named 'pymysql'` | Connection thật dùng `mysql+pymysql://`, image 5.0.0 không có driver | `docker/requirements-local.txt` + `docker/wheels/` (cài offline được) |
| `1045 Access denied for user ...@<IP>` ở Lab 2 | Data server chỉ cấp quyền cho IP Lab 1 | DBA cấp quyền cho IP Lab 2 |
| `permission denied for table ab_role` sau rollback | Restore bằng `postgres` | Restore bằng `-U superset` (mục 5) |
| Dashboard thành "chưa xuất bản", user thường không thấy | 2.1.1 không export `published` | `sync_dashboard_published.py` |
| Role mặc định phình quyền | Import nguyên file `export-roles` | `filter_roles.py` |
| `Invalid decryption key` | `SECRET_KEY` không đúng key đã mã hoá metadata | Điền đúng key thật của lab đó trong `.env` |
| Restore dump Lab 1 lỗi `near 'SEQUENCE=1'` | Restore vào MySQL 8 | Dùng `mariadb:10.3.32` (`LAB1_META_IMAGE`), đổi engine phải xoá volume |

**Giới hạn còn mở:**
- Owner của object import đều thành user chạy import, chưa có script map owner theo `username`.
- Quyền theo từng dataset/database của role tự tạo chưa tự chuyển.
- Trùng tên connection nhưng khác UUID thì import báo lỗi, phải đổi tên một bên trước.
- Chỉ import được từ version cũ sang version mới hơn hoặc bằng.

## 8. Cấu trúc thư mục

```
docker-compose.yml        5 container (mục 1)
.env.example              mẫu cấu hình: SECRET_KEY, version, image, port
docker/                   Dockerfile + requirements-local.txt + wheels/ (driver, cài được khi không có internet)
superset/                 superset_config.py (đọc env), bootstrap.sh (db upgrade -> create-admin -> init -> gunicorn)
initdb/                   SQL tạo DB/user/data, chỉ chạy khi volume trống
sync/                     BỘ CÔNG CỤ MIGRATE, dùng cho cả lab lẫn prod (mount /app/sync)
  export_databases.py       export mọi connection
  export_bundle.py          export mọi dataset / dashboard với user tự chọn
  export_db_passwords.py    giải mã mật khẩu connection ra JSON
  import_bundle_direct.py   import database / dataset / dashboard trong tiến trình, kèm mật khẩu
  filter_roles.py           lọc file export-roles, chỉ giữ role tự tạo
  sync_users.py             thêm user (khớp username, giữ hash, role theo tên)
  sync_dashboard_published.py  chép cờ published theo UUID
  sync_query_history.py     copy query + saved query, map user và connection theo tên
  check_connections.py      thử kết nối từng connection
  check_queries.py          EXPLAIN saved query / lịch sử query, so hai lab
  verify_merge.py           snapshot trước, kiểm tra sau
  meta_db.py                hàm dùng chung để ghi vào metadata đích
fake_data/                seed data giả cho lab + smoke_test_api.py; các bản sync_* trong đây là bản cũ
scripts/                  merge_lab1_to_lab2.sh (tự động, bản cũ), reset_lab2.sh, verify.sh
backup/                   file export / backup (không commit)
```

`scripts/merge_lab1_to_lab2.sh` và `scripts/verify.sh` vẫn gọi bản cũ trong `fake_data/`: không có bước `databases.zip`, và dùng mật khẩu mặc định `reader_pwd` khi thiếu. Chúng chỉ dùng cho lab. Prod chạy tay theo mục 4.

## 9. Diễn tập với dữ liệu thật

Lab ở trên dùng data giả. Khi diễn tập với dump/backup thật, xem [docs/REHEARSAL_VM_CONDA.md](docs/REHEARSAL_VM_CONDA.md). Những điểm chính:

- **Dựng ở thư mục khác, ngoài repo này.** Repo đã push GitHub; dump thật chứa mật khẩu đã mã hoá và thông tin nhân viên. Nếu buộc phải để trong repo, kiểm tra `git status` để chắc chắn file dump và `backup/` không bị add.
- **Restore dump Lab 1 vào `mysql_lab1`:** dump không có `CREATE DATABASE` / `USE`, nên phải chỉ định DB đích, và chỉ restore khi container đã `healthy`:
  ```bash
  docker compose up -d mysql_lab1          # chưa bật superset_lab1
  docker exec -i mysql_lab1 mysql -uroot -proot superset_meta < <file_dump>.sql
  ```
- `.env` phải có **SECRET_KEY thật** của Lab 1 (và Lab 2 nếu restore backup Lab 2).
- `superset/bootstrap.sh` chạy `create-admin` và `superset init` mỗi lần container khởi động, nên sẽ thêm user `admin` giả và đồng bộ lại quyền trên metadata vừa restore. Metadata diễn tập vì vậy hơi lệch prod.
- Superset chạy bằng conda ngoài Docker phải nối tới DB qua cổng publish ra `127.0.0.1`, không dùng tên container được.
