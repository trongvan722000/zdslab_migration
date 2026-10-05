# Diễn tập migrate với dữ liệu thật: VM + conda (Superset) + Docker (database)

> Tài liệu riêng, **tách biệt khỏi lab thực hành** (README.md, MIGRATION_GUIDE.md) vì từ đây trở đi làm việc với **dữ liệu production thật** (dump/backup metadata, mật khẩu mã hoá thật, email nhân viên thật) — không phải data giả nữa. Đọc [PRODUCTION_RUNBOOK.md](PRODUCTION_RUNBOOK.md) trước để biết đầy đủ 8 bước migrate; tài liệu này chỉ nói **môi trường chạy khác thế nào** khi Superset không nằm trong Docker mà chạy bằng conda trên VM.

## 0. Vì sao cần tài liệu riêng

Lab thực hành (`docker-compose.yml` ở gốc repo) chạy **toàn bộ bằng Docker**: cả Superset lẫn database đều là container, cùng một Docker network, gọi nhau bằng tên service.

Môi trường thật (theo dấu hiệu đã thấy trong config Lab 1: `sys.path.append('/home/.../anaconda3/envs/zdslab-new/...')`) lại chạy Superset bằng **conda trên VM**, không phải Docker. Muốn diễn tập sát thật, môi trường rehearsal phải theo đúng kiểu này — nhưng vẫn tiện dùng Docker cho phần database vì đó chỉ là kho chứa tạm, không ảnh hưởng tới việc kiểm chứng cách Superset (ứng dụng) vận hành.

**Nguyên tắc bắt buộc: KHÔNG dựng bất kỳ thứ gì ở trên trong thư mục `zdslab_migration` này.** Repo này đã push lên GitHub của bạn; nếu dump/backup thật (chứa secret thật) lọt vào đây, rủi ro lặp lại đúng sự cố từng gặp (`backup/passwords.json` bị lỡ commit) — lần này với dữ liệu thật. Dựng ở một thư mục/VM hoàn toàn khác, ví dụ `~/rehearsal/` trên VM dev.

## 1. Kiến trúc

```
Ubuntu VM (dev, tách biệt khỏi lab thực hành)
├── Docker
│   ├── container MariaDB 10.3.32 → khôi phục dump Lab 1 thật (đúng version thật)
│   └── container Postgres 14    → khôi phục backup Lab 2 thật (đúng version thật)
└── conda
    ├── env Superset 2.1.1 (Lab 1) — pip install apache-superset==2.1.1 pymysql mysqlclient
    └── env Superset 5.0.0 (Lab 2) — pip install apache-superset==5.0.0 psycopg2-binary
```

Engine/version DB phải khớp bản thật (đã xác nhận: **MariaDB 10.3.32** cho metadata Lab 1, Postgres 14 cho Lab 2) — khác version có thể đổi collation mặc định và che giấu hoặc tạo ra lỗi giả (xem bẫy #2, #22, #23 trong `MIGRATION_GUIDE.md`, vốn xảy ra chính vì khác biệt MySQL/Postgres).

> **Lab 1 là MariaDB, không phải MySQL**, dù config ghi `mysql+pymysql://` và mọi người gọi là "MySQL" (MariaDB dùng chung giao thức nên client không phân biệt). Xác nhận bằng `SELECT VERSION();` → `10.3.32-MariaDB-log`, hoặc header dump `Server version 5.5.5-10.3.32-MariaDB-log`. Hệ quả: dump có 8 bảng **SEQUENCE** của MariaDB (`ab_permission_id_seq`, `ab_role_id_seq`, `ab_user_id_seq`, …; khai báo `ENGINE=InnoDB SEQUENCE=1`) và 7 bảng `ab_*` lấy id từ đó (cột `id` không có `AUTO_INCREMENT`). Restore vào MySQL 8 sẽ lỗi `ERROR 1064 ... near 'SEQUENCE=1'`; sửa dump cho lọt thì Superset lại lỗi `Field 'id' doesn't have a default value` khi thêm role/permission. Luôn restore vào đúng `mariadb:10.3.32`.

## 2. Chuẩn bị trước khi bắt đầu

| Cần | Lấy ở đâu |
|---|---|
| Tài khoản **chỉ đọc** vào metadata Lab 1 thật (MariaDB 10.3.32, DB tên `zdslab`) | Xin admin Lab 1 |
| `SECRET_KEY` thật của Lab 1 | Xin người giữ config Lab 1 (cần để giải mã mật khẩu connection trong dump) |
| Backup thật của Lab 2 (Postgres) + `SECRET_KEY` thật của Lab 2 | Xin admin Lab 2 (việc xin quyền này tách biệt, y như xin dump Lab 1) |
| `SHOW CREATE DATABASE zdslab\G` trên Lab 1 thật | Để lấy đúng collation, tạo DB rehearsal giống hệt |
| `SELECT version();` trên Postgres Lab 2 thật | Xác nhận đúng major version (14) trước khi cài |
| Một VM/server test **được duyệt**, không phải laptop cá nhân | Xin hạ tầng cấp |

## 3. Dựng 2 database bằng Docker

Tạo thư mục **hoàn toàn tách biệt** trên VM, ví dụ `~/rehearsal/`:

```yaml
# ~/rehearsal/docker-compose.yml
services:
  mysql_lab1:
    image: mariadb:10.3.32   # đúng engine/version Lab 1 thật, KHÔNG phải mysql:8
    container_name: rehearsal_mysql_lab1
    environment:
      MYSQL_ROOT_PASSWORD: <pw>
    ports: ["3310:3306"]
    volumes: ["mysql_lab1_data:/var/lib/mysql"]

  postgres_lab2:
    image: postgres:14
    container_name: rehearsal_postgres_lab2
    environment:
      POSTGRES_PASSWORD: <pw>
    ports: ["5440:5432"]
    volumes: ["postgres_lab2_data:/var/lib/postgresql/data"]

volumes:
  mysql_lab1_data:
  postgres_lab2_data:
```

```bash
cd ~/rehearsal && docker compose up -d
```

## 4. Dump Lab 1 thật, restore vào MariaDB rehearsal

```bash
# Trên Lab 1 thật, tài khoản chỉ đọc, không khoá bảng
mysqldump -h <host_lab1_thật> -u <user_ro> -p \
  --single-transaction --set-gtid-purged=OFF --routines --triggers \
  zdslab > lab1_prod_dump_$(date +%F_%H%M).sql
sha256sum lab1_prod_dump_*.sql | tee lab1_prod_dump.sha256
chmod 600 lab1_prod_dump_*.sql

# Chuyển sang VM rehearsal (không giữ bản thứ 2 ở máy vừa dump)
scp lab1_prod_dump_*.sql <vm_dev>:~/rehearsal/
rm -f lab1_prod_dump_*.sql

# Trên VM rehearsal: tạo DB đúng tên + collation thật, rồi restore
docker exec -i rehearsal_mysql_lab1 mysql -uroot -p<pw> -e \
  "CREATE DATABASE zdslab CHARACTER SET utf8mb4 COLLATE <collation_thật_đã_lấy>"
docker exec -i rehearsal_mysql_lab1 mysql -uroot -p<pw> zdslab < ~/rehearsal/lab1_prod_dump_<ts>.sql
```

## 5. Backup Lab 2 thật, restore vào Postgres rehearsal

```bash
docker exec -i rehearsal_postgres_lab2 createdb -U postgres -O postgres <ten_db_lab2_thật>
docker exec -i rehearsal_postgres_lab2 psql -U postgres -d <ten_db_lab2_thật> -f - < lab2_prod_backup.sql
```

## 6. Dựng Superset bằng conda — điểm dễ sai nhất

**Superset chạy ngoài Docker network**, nên phải nối tới 2 DB qua **cổng đã publish ra `127.0.0.1`**, không dùng được tên container (`mysql_lab1`, `postgres_lab2`) như trong `docker-compose.yml` của lab thực hành. Quên đổi chỗ này sẽ thấy lỗi "Unknown host"/"Connection refused" và dễ tưởng nhầm là lỗi migrate.

```bash
# --- Superset 2.1.1 cho Lab 1 (chỉ đọc, để export) ---
conda create -n rehearsal_lab1 python=3.9 -y
conda activate rehearsal_lab1
pip install apache-superset==2.1.1 pymysql mysqlclient

export SUPERSET_SECRET_KEY="<SECRET_KEY thật của Lab 1>"
export SQLALCHEMY_DATABASE_URI="mysql+pymysql://root:<pw>@127.0.0.1:3310/zdslab"
superset db upgrade   # nếu cần đồng bộ schema trước khi export (thường không cần vì dump đã đúng schema)

# --- Superset 5.0.0 cho Lab 2 (đích import) ---
conda create -n rehearsal_lab2 python=3.10 -y
conda activate rehearsal_lab2
pip install apache-superset==5.0.0 psycopg2-binary

export SUPERSET_SECRET_KEY="<SECRET_KEY thật của Lab 2>"
export SQLALCHEMY_DATABASE_URI="postgresql+psycopg2://postgres:<pw>@127.0.0.1:5440/<ten_db_lab2_thật>"
```

## 7. Chạy migrate — cùng logic Bước 0→8, khác cách gọi lệnh

Không có `docker exec <container> python ...` nữa — activate đúng conda env rồi chạy thẳng script Python (copy `fake_data/*.py` từ repo này sang VM, ví dụ `scp -r fake_data <vm_dev>:~/rehearsal/`):

```bash
conda activate rehearsal_lab1
python ~/rehearsal/fake_data/export_db_passwords.py ~/rehearsal/passwords.json
superset export-datasources -f ~/rehearsal/datasources.zip
superset export-dashboards  -f ~/rehearsal/dashboards.zip

conda activate rehearsal_lab2
python ~/rehearsal/fake_data/import_bundle_direct.py dataset   ~/rehearsal/datasources.zip admin
python ~/rehearsal/fake_data/import_bundle_direct.py dashboard ~/rehearsal/dashboards.zip  admin
# SRC_META_URI trỏ về 127.0.0.1:3310 (không phải mysql_lab1) khi chạy sync_users.py / sync_query_history.py / verify_merge.py
```

Nội dung/ý nghĩa từng bước (Bước 0-8, thứ tự, cách đọc kết quả) giữ nguyên như `PRODUCTION_RUNBOOK.md` mục 7 — chỉ khác câu lệnh gọi như trên.

## 8. Dọn dẹp sau khi test xong (bắt buộc — có dữ liệu thật)

```bash
cd ~/rehearsal && docker compose down -v         # xoá cả 2 container lẫn volume chứa data thật
conda env remove -n rehearsal_lab1
conda env remove -n rehearsal_lab2
shred -u ~/rehearsal/*.sql ~/rehearsal/*.json ~/rehearsal/*.zip 2>/dev/null || \
  rm -f ~/rehearsal/*.sql ~/rehearsal/*.json ~/rehearsal/*.zip
```

Không để lại container, volume, hay file nào chứa dữ liệu thật trên VM sau khi xong việc.
