# Tài liệu migrate metadata Superset: Lab 1 → Lab 2

| | |
|---|---|
| Nguồn (Lab 1) | Apache Superset **2.1.1**, metadata trong MySQL |
| Đích (Lab 2) | Apache Superset **5.0.0**, metadata trong **Postgres** (khác engine với Lab 1), **đang có sẵn dữ liệu riêng cần giữ** |
| Data thật | MySQL và Postgres, **không di chuyển**, cả hai lab cùng truy vấn vào đó |
| Trạng thái | Đã thử trọn quy trình trên môi trường lab mô phỏng (Docker). **Chưa chạy trên hệ thống thật.** |
| Ngày cập nhật | 25/09/2026 |

> **Làm migrate thật (production): xem [PRODUCTION_RUNBOOK.md](PRODUCTION_RUNBOOK.md).** Tài liệu này là lý thuyết và lab; runbook là quy trình cho hệ thống thật.

Tài liệu gồm: **Phần I** lý thuyết cần hiểu; **Phần II** môi trường lab; **Phần III** các bước thực hiện; **Phần IV** kiểm chứng, rollback, reset; **Phần V** bẫy và bài học đã gặp; **Phần VI** áp dụng cho production; **Phần VII** những điều chưa kiểm chứng; **Phụ lục** bản đồ repo và FAQ.

## Mục lục

- [0. Tóm tắt](#0-tóm-tắt)
- **Phần I. Lý thuyết**
  - [1. Superset gồm những gì](#1-superset-gồm-những-gì)
  - [2. Metadata là gì, gồm những bảng nào](#2-metadata-là-gì-gồm-những-bảng-nào)
  - [3. ID và UUID: vì sao "gộp" khó](#3-id-và-uuid-vì-sao-gộp-khó)
  - [4. Bảo mật: mã hoá, hash và SECRET_KEY](#4-bảo-mật-mã-hoá-hash-và-secret_key)
  - [5. Version, alembic và `superset db upgrade`](#5-version-alembic-và-superset-db-upgrade)
  - [6. Export / import bundle hoạt động thế nào](#6-export--import-bundle-hoạt-động-thế-nào)
  - [7. Những thứ không có lệnh export](#7-những-thứ-không-có-lệnh-export)
  - [8. Hai phương án và trade-off](#8-hai-phương-án-và-trade-off)
  - [9. Bản đồ: cái gì đi bằng đường nào](#9-bản-đồ-cái-gì-đi-bằng-đường-nào)
- **Phần II. Môi trường lab**
- **Phần III. Các bước thực hiện (runbook)**
- **Phần IV. Kiểm chứng, rollback, reset**
- **Phần V. Bẫy và bài học đã gặp**
- **Phần VI. Áp dụng cho production**
- **Phần VII. Chưa kiểm chứng**
- **Phụ lục A. Bản đồ repo · B. FAQ · C. Lệnh hữu ích**

---

## 0. Tóm tắt

**Bài toán.** Lab 1 (Superset 2.1.1) cấu hình cũ, hay phát sinh lỗi vặt. Cần chuyển toàn bộ *cấu hình báo cáo* (metadata) sang Lab 2 (Superset 5.0.0). Lab 2 đã có user, connection, dataset, dashboard riêng nên **phải giữ nguyên**, chỉ *thêm* phần của Lab 1.

**Quyết định.** Không sao chép nguyên database metadata (dump/restore) vì nó ghi đè toàn bộ Lab 2. Dùng **export/import của Superset** cho connection, dataset, chart, dashboard; và **script copy dòng** cho những thứ Superset không có lệnh export (user, lịch sử query, saved query, cờ xuất bản dashboard).

**Kết quả thử.** Trên lab: merge 2.1.1 → 5.0.0 thành công, chạy lại lần hai không tạo trùng, mọi dữ liệu cũ của Lab 2 còn nguyên, 7/7 connection kết nối được, 13/13 chart ra số liệu, user cũ của Lab 1 đăng nhập được ở Lab 2 bằng mật khẩu cũ.

---

# Phần I. Lý thuyết

## 1. Superset gồm những gì

```
                     ┌────────────────────────────┐
   người dùng ─────► │  Ứng dụng web Superset     │
   (trình duyệt)     │  (Python, chạy trong       │
                     │   container / máy chủ)     │
                     └──────┬──────────────┬──────┘
                            │              │
              đọc/ghi cấu hình              │ chạy query khi
                            │              │ mở dashboard / SQL Lab
                            ▼              ▼
                ┌────────────────┐   ┌────────────────────┐
                │ METADATA DB    │   │ DATA DB (nhiều cái)│
                │ (MySQL/PG)     │   │ MySQL, Postgres... │
                │ tên: superset_ │   │ số liệu kinh doanh │
                │ meta           │   │ thật               │
                └────────────────┘   └────────────────────┘
```

| Thành phần | Chứa gì | Có di chuyển khi migrate không? |
|---|---|---|
| **Ứng dụng Superset** | Code + cấu hình chạy (`superset_config.py`, `SECRET_KEY`) | Không. Lab 2 là một instance riêng, đã có sẵn |
| **Metadata DB** | Cấu hình báo cáo: connection, dataset, chart, dashboard, user, lịch sử query... | **Có, đây là thứ cần chuyển** |
| **Data DB** | Số liệu thật mà Superset truy vấn | **Không.** Cả hai lab cùng trỏ vào |

Điểm mấu chốt: Superset *không lưu số liệu*. Nó chỉ lưu "công thức" (kết nối nào, bảng nào, biểu đồ vẽ thế nào) trong metadata, còn số liệu được truy vấn trực tiếp từ data DB mỗi lần mở.

## 2. Metadata là gì, gồm những bảng nào

| Đối tượng | Bảng trong metadata | Ghi chú |
|---|---|---|
| Connection tới data DB | `dbs` | Có cột `password` (mã hoá) và `sqlalchemy_uri` (đã che mật khẩu) |
| Dataset | `tables` | Mỗi dòng trỏ tới `dbs` qua `database_id` |
| Cột và metric của dataset | `table_columns`, `sql_metrics` | Trỏ tới `tables` qua `table_id` |
| Chart | `slices` | Trỏ tới dataset qua `datasource_id` |
| Dashboard | `dashboards` | Cột `published`, `position_json` (bố cục) |
| Chart nào nằm trong dashboard nào | `dashboard_slices` | Bảng nối |
| Người tạo (owner) | `dashboard_user`, `slice_user`, `sqlatable_user` | Bảng nối tới `ab_user` |
| User | `ab_user` | Cột `password` là **hash** |
| Nhóm quyền | `ab_role`, `ab_user_role` | Gán quyền theo role |
| Lịch sử query SQL Lab | `query` | Mỗi lần chạy query trong SQL Lab là một dòng |
| Query đã lưu | `saved_query` | |
| Tab SQL Lab đang mở | `tab_state`, `table_schema` | Không migrate |
| Phiên bản schema | `alembic_version` | Một dòng, ghi "head" hiện tại |

Quan hệ chính (mũi tên = "trỏ tới bằng ID"):

```
dbs ◄── tables ◄── slices ──► dashboard_slices ──► dashboards
                     ▲                                  ▲
                     └──────── owner (ab_user) ─────────┘
query ──► dbs, ab_user        saved_query ──► dbs, ab_user
ab_user ◄──► ab_user_role ◄──► ab_role
```

## 3. ID và UUID: vì sao "gộp" khó

Mọi bảng dùng **ID số tự tăng** (1, 2, 3...) làm khoá chính, và các bảng tham chiếu nhau bằng ID đó (chart nói "tôi dùng dataset số 3").

Vấn đề: **Lab 1 và Lab 2 đều đánh số từ 1.**

| | Lab 1 | Lab 2 (đã có sẵn) |
|---|---|---|
| `dbs.id = 1` | MySQL - Sales | Lab2 - Legacy Sales |
| `tables.id = 1` | orders (của Lab 1) | orders (của Lab 2) |
| `ab_user.id = 2` | zds_alice | lab2_nam |

Nếu đổ đè dữ liệu Lab 1 vào Lab 2 thì hoặc trùng khoá chính (báo lỗi), hoặc nếu ép ghi đè thì chart của Lab 1 trỏ nhầm vào dataset của Lab 2 và owner bị đổi người, mà **không báo lỗi gì**.

**Lối thoát: UUID.** Mỗi object (connection, dataset, chart, dashboard) còn có một `uuid` cố định, sinh một lần và đi theo object. Cơ chế export/import của Superset nhận diện object bằng UUID:
- UUID chưa có ở đích → tạo mới, **cấp ID mới** ở đích và tự nối lại các tham chiếu.
- UUID đã có ở đích → coi là cùng object và cập nhật (khi `overwrite=true`), nên chạy lại không tạo bản trùng.

Với thứ không có UUID hoặc không có lệnh export (user, query history), ta tự **map lại ID theo một khoá tự nhiên**: user theo `username`, connection theo **tên**, role theo **tên role**.

## 4. Bảo mật: mã hoá, hash và SECRET_KEY

Đây là phần dễ nhầm nhất. Có ba thứ khác nhau:

| Dữ liệu | Dạng lưu | Đảo ngược được? | Phụ thuộc `SECRET_KEY`? |
|---|---|---|---|
| **Mật khẩu connection** (`dbs.password`, `encrypted_extra`) | **Mã hoá hai chiều** | Có, nếu có đúng key | **Có** |
| **Mật khẩu user** (`ab_user.password`) | **Hash một chiều** (muối nằm trong chuỗi hash) | **Không** | Không |
| **File ZIP export** | **Không chứa mật khẩu** (chỉ còn `reader:XXXXXXXXXX@host`) | (không có gì để đảo) | Không |

### 4.1. Mật khẩu connection: mã hoá hai chiều

Superset cần mật khẩu *gốc* để đăng nhập vào MySQL/Postgres, nên không thể hash một chiều. Nó mã hoá bằng `SECRET_KEY` khi lưu và giải mã khi dùng.

Trong code Superset (cả 2.1.1 và 5.0.0), cột được khai báo:

```python
password = Column(encrypted_field_factory.create(String(1024)))   # superset/models/core.py
```

Kiểu cột này **tự mã hoá khi ghi, tự giải mã khi đọc** bằng `SECRET_KEY` của ứng dụng. Vì vậy trong code, `d.password` (với `d` là một dòng của `dbs`) trả ra chữ thường, trong khi trong database chỉ là `JGo8M2E+tS4nYsn1hEa+5A==`.

Đã thử thật trên lab: giải mã cùng một giá trị bằng đúng `SECRET_KEY` cho ra `reader_pwd`, bằng key sai thì báo lỗi `ValueError`.

**`SECRET_KEY` nằm ở đâu trong repo:**

| Nơi | Nội dung |
|---|---|
| `docker-compose.yml` | `SUPERSET_SECRET_KEY_LAB1` / `SUPERSET_SECRET_KEY_LAB2`, mỗi Superset một biến riêng, **giá trị khác nhau** |
| `superset/superset_config.py` | `SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]` |

Chuỗi: biến môi trường của container → `superset_config.py` đọc thành `SECRET_KEY` → Superset dùng làm chìa khoá.

**Hệ quả cho migrate:**
- Mỗi lab dùng key của chính nó. Hai lab có thể có key khác nhau.
- Vì key khác nhau, không thể chép nguyên giá trị mã hoá từ Lab 1 sang Lab 2 rồi kỳ vọng Lab 2 giải mã được. Cách làm ở repo này: lấy mật khẩu *chữ thường* ra khỏi Lab 1 (nhờ Superset giải mã), gửi cho Lab 2 lúc import, Lab 2 **tự mã hoá lại bằng key của nó**.
- Với phương án dump/restore (chép nguyên database), key hai bên **bắt buộc phải giống nhau**, nếu không mọi connection lỗi giải mã.
- Lab này cố tình đặt **hai key khác nhau** giữa Lab 1 và Lab 2 (giống thực tế production), và đã chạy thử thật: export 5 mật khẩu từ Lab 1 (giải mã bằng key Lab 1), import vào Lab 2 (mã hoá lại bằng key Lab 2 khác hẳn) — cả 7 connection sau merge vẫn `connect OK`. Xác nhận key khác nhau không phải vấn đề với cách import hiện tại.

### 4.2. Mật khẩu user: hash một chiều

`ab_user.password` là hash (dạng `pbkdf2:sha256:...$muối$chuỗi`). Không thứ gì giải mã được, kể cả `SECRET_KEY`. Khi đăng nhập, Superset hash mật khẩu vừa gõ theo đúng thuật toán và muối **nằm ngay trong chuỗi hash đã lưu**, rồi so sánh.

Nên khi migrate chỉ cần **chép nguyên chuỗi hash** sang Lab 2. `sync_users.py` làm đúng vậy. User cũ đăng nhập Lab 2 bằng mật khẩu cũ mà không ai biết mật khẩu đó là gì. Đã thử: `zds_alice` (chuyển từ Lab 1 2.1.1) đăng nhập được ở Lab 2 5.0.0.

Điều kiện: Lab 2 phải hiểu định dạng hash của Lab 1. Bản mới đọc được hash của bản cũ (đã thử 2.1.1 → 5.0.0); chiều ngược lại chưa chắc. User đăng nhập bằng LDAP/SSO/OAuth không có mật khẩu trong `ab_user`, phần này không áp dụng với họ.

### 4.3. File nào chứa mật khẩu ở dạng nào

| File | Mật khẩu | Lưu trữ lâu dài được không |
|---|---|---|
| `datasources.zip`, `dashboards.zip` | Không có | Được |
| Backup metadata (`mysqldump`) | Connection: vẫn mã hoá. User: hash | Tương đối an toàn nếu `SECRET_KEY` không nằm cùng chỗ |
| **`passwords.json`** (do `export_db_passwords.py` tạo) | **Chữ thường** | **Không.** Xoá ngay sau khi dùng |

### 4.4. Ý nghĩa bảo mật

Mã hoá này bảo vệ dữ liệu *khi nằm trong database* (ai chỉ lấy được bản backup database thì không đọc được). Nhưng ai có **cả** quyền truy cập container/cấu hình (`SECRET_KEY`) **và** database thì lấy được mật khẩu. Do đó: `SECRET_KEY` phải được giữ kín như mật khẩu, chỉ người quản trị mới chạy `export_db_passwords.py`, và file chữ thường phải bị xoá ngay.

## 5. Version, alembic và `superset db upgrade`

- Bảng `alembic_version` ghi phiên bản schema của metadata. Lab 1 (2.1.1) có head `9c2a5681ddfd`, Lab 2 (5.0.0) có head `74ad1125881c`. Hai schema khác nhau (5.0.0 có thêm cột, đổi tên cột...).
- `superset db upgrade` đưa schema của metadata lên phiên bản của ứng dụng đang chạy. **Chỉ đi theo một chiều, từ cũ lên mới.** Không hạ ngược được.
- `superset init` đồng bộ role và permission (tạo permission cho connection/dataset mới, cập nhật role mặc định).
- Vì hai lab khác version và khác schema, **dump/restore giữa 2.1.1 và 5.0.0 là hướng rủi ro cao và chưa được thử trong lab**: sau khi restore phải chạy `superset db upgrade` để nâng schema qua nhiều bản lớn (2.1 → 5.0), có thể lỗi ở giữa chừng; ngoài ra nó còn ghi đè toàn bộ Lab 2. Export/import dùng định dạng YAML ổn định giữa các version, nên chạy được (đã thử).
- Ở Lab 2 (5.0.0) `db upgrade` tự chạy khi container khởi động (`superset/bootstrap.sh`). Với cách import, dữ liệu của Lab 1 không đi qua schema cũ mà được nạp qua chính ứng dụng 5.0.0, nên không cần nâng schema riêng cho dữ liệu Lab 1.

Nguyên tắc: chỉ migrate từ version cũ sang version mới hơn hoặc bằng.

## 6. Export / import bundle hoạt động thế nào

**Bundle** là file ZIP do Superset export, bên trong là các file YAML:

```
dashboard_export_<timestamp>/
  metadata.yaml            # loại export (ví dụ Dashboard), version định dạng, thời điểm
  databases/<tên>.yaml     # connection: tên, sqlalchemy_uri (đã che mật khẩu), uuid, extra
  datasets/<db>/<bảng>.yaml
  charts/<tên>_<id>.yaml
  dashboards/<tên>_<id>.yaml
```

Hai lệnh export ở Lab 1:

| Lệnh | Chứa gì |
|---|---|
| `superset export-datasources -f ...zip` | Connection + dataset (`databases/` và `datasets/`) |
| `superset export-dashboards -f ...zip` | Dashboard + chart, **kèm** dataset và connection mà chúng dùng |

Vì file dashboard đã kèm dataset và connection nên hai file trùng nhau một phần. File `datasources.zip` cần thiết để lấy thêm dataset/connection **không nằm trong dashboard nào**. Import cả hai vẫn an toàn nhờ UUID.

### 6.1. Vì sao import trực tiếp trong tiến trình, không dùng lệnh `superset import-dashboards` hay REST API

- File export **không chứa mật khẩu connection**.
- Lệnh CLI `import-dashboards` / `import-datasources` **không cho truyền mật khẩu**, nên bị từ chối ở bước validate (đã thử, lỗi `CommandInvalidError`).
- Cách chính thức còn lại của Superset là REST API: `POST /api/v1/dataset/import/` và `POST /api/v1/dashboard/import/` nhận thêm trường `passwords` (JSON `{"databases/<file>.yaml": "mật khẩu"}`) và `overwrite` — nhưng gọi API thì phải **đăng nhập trước** (token), khó tự động hoá khi mật khẩu đăng nhập là OTP (mục 3.3).

**Cách dùng trong repo này:** `fake_data/import_bundle_direct.py` gọi thẳng lệnh import của Superset (chính là đoạn code xử lý bên trong hai API endpoint trên) ngay trong tiến trình ứng dụng, kèm `passwords`. Không qua web, không cần đăng nhập/OTP/token, không dính timeout HTTP. Đã thử trên lab, là cách khuyến nghị duy nhất cho production (xem PRODUCTION_RUNBOOK mục 3.3). **File ZIP không bị sửa**; mật khẩu đi riêng, Lab 2 nhận rồi tự mã hoá và lưu vào metadata của nó.

### 6.2. Chọn mật khẩu cho từng connection

`import_bundle_direct.py` tìm mật khẩu theo **tên connection**, theo thứ tự ưu tiên:
1. File JSON tại đường dẫn trong `DB_PASSWORDS_FILE` (`{"MySQL - Sales": "pwd1", ...}`), dùng khi có nhiều connection.
2. Biến `DB_PASSWORDS_JSON` (cùng dạng, gõ trực tiếp).
3. Biến `DB_PASSWORD`: dùng cho mọi connection không có trong hai nguồn trên (mặc định `reader_pwd`, chỉ đúng trong lab vì cả 5 connection dùng chung tài khoản `reader`).

Connection nào rơi vào mục 3 sẽ in dòng `note: no specific password for ...`.

### 6.3. Nguồn mật khẩu

- Lab: `reader_pwd` chỉ là mật khẩu của tài khoản `reader` mà `initdb/*` tạo.
- Nhiều connection (ví dụ 43): dùng `fake_data/export_db_passwords.py`, chạy **trong container Lab 1**, để chính Superset giải mã rồi ghi ra file JSON. Cơ chế: dòng `for d in db.session.query(Database): result[d.database_name] = d.password`, trong đó `d.password` tự giải mã (mục 4.1). Script tạo app bằng `create_app()` để nạp `SECRET_KEY` của Lab 1.
- Hoặc tự lập file JSON từ kho mật khẩu của công ty (không giải mã gì trong hệ thống).

### 6.4. Superset 5.0.0 kiểm tra kết nối khi import

Khi nạp dataset, 5.0.0 kết nối thử tới database để lấy danh sách cột. Do đó **mật khẩu sai bị từ chối ngay** (HTTP 500, log `password authentication failed`), không lưu âm thầm. Đây là lưới an toàn có ích, nhưng không nên trông chờ với version cũ hơn; hãy luôn chạy bước kiểm chứng.

## 7. Những thứ không có lệnh export

Superset không có lệnh export cho các mục sau, nên ta **copy dòng trực tiếp** giữa hai metadata DB (đọc từ Lab 1, ghi vào Lab 2), mỗi mục có một chiến lược map ID riêng:

| Mục | Script | Khớp (chống trùng) | Map ID theo |
|---|---|---|---|
| **User** | `sync_users.py` | `username` | Role gán theo **tên role**; giữ nguyên chuỗi hash |
| **Lịch sử query** (`query`) | `sync_query_history.py` | `client_id` | user_id → theo `username`; database_id → theo **tên connection** |
| **Saved query** (`saved_query`) | `sync_query_history.py` | `uuid` | user → theo `username`; db_id → theo tên connection |
| **Cờ xuất bản dashboard** | `sync_dashboard_published.py` | `uuid` | (không cần map, chỉ cập nhật cờ) |

Lưu ý riêng:
- **Lịch sử query chỉ mang được phần "nhật ký"**: ai chạy, SQL gì, lúc nào, thành công hay lỗi (giữ nguyên thời gian gốc). **Không mang theo kết quả đã cache** (`results_key` được đặt NULL, vì nó trỏ vào nơi lưu tạm của Lab 1). Muốn xem số liệu thì chạy lại query.
- Dòng lịch sử nào có connection không tồn tại ở Lab 2 sẽ bị bỏ qua kèm cảnh báo. Vì vậy script này **phải chạy sau khi import connection** và sau khi thêm user.
- Cờ `published` phải sync vì export của Superset 2.1.x **không chứa trường này**, xem Phần V.
- Owner (người tạo) của chart/dashboard/dataset **không được giữ**: mọi thứ import vào thuộc user chạy import (`admin`). Nếu cần giữ owner gốc phải làm thêm một bước map theo `username`.

## 8. Hai phương án và trade-off

**Phương án A: Sao chép nguyên cả database metadata** (`mysqldump` Lab 1 → restore vào Lab 2).
**Phương án B: Export/import từng loại + script copy dòng** (phương án chọn).

| | A. Dump / restore | B. Export / import + script |
|---|---|---|
| Giữ dữ liệu đang có của Lab 2 | **Không.** Ghi đè toàn bộ | **Có.** Chỉ thêm vào |
| Số bước, độ phức tạp | **Ít, nhanh** | Nhiều bước hơn |
| Giống bản gốc | **100%** (cả owner, lịch sử, ID) | Không giữ owner gốc; không mang cache kết quả |
| Khác version (2.1.1 → 5.0.0) | Phải nâng schema bằng `db upgrade` sau khi restore, nhảy nhiều bản lớn; **chưa thử, rủi ro cao** | Dùng được, **đã thử** (YAML ổn định giữa các version), nhưng có thể thiếu vài trường (Phần V, bẫy #1) |
| Mật khẩu connection | Theo sang nguyên; **hai bên phải chung `SECRET_KEY`** | Phải cung cấp lại lúc import; hai bên khác key vẫn được |
| Chạy lại khi sai | Chạy lại là ghi đè tiếp | **Chạy lại an toàn**, không tạo trùng |
| Khi nào hợp | Lab 2 đang **trống**, cùng version | Lab 2 **đã có dữ liệu** cần giữ, hoặc khác version |

**Kết luận: chọn B**, vì Lab 2 đang có dữ liệu cần giữ (lý do chính), và hai bên khác version nên A còn kèm rủi ro nâng cấp schema chưa thử. A chỉ nên cân nhắc nếu Lab 2 trống.

Ghi chú: nếu Lab 2 trống và cùng version thì phương án A (dump/restore) nhanh và giống bản gốc hơn. Trong dump/restore phải chạy `superset db upgrade` sau khi restore và restart container.

## 9. Bản đồ: cái gì đi bằng đường nào

| Cần chuyển | Đường đi | Công cụ |
|---|---|---|
| Connection + dataset | Export ZIP → import trực tiếp trong tiến trình kèm mật khẩu | `superset export-datasources` + `import_bundle_direct.py dataset` |
| Dashboard + chart (kèm dataset, connection liên quan) | Export ZIP → import trực tiếp trong tiến trình kèm mật khẩu | `superset export-dashboards` + `import_bundle_direct.py dashboard` |
| Mật khẩu connection | Giải mã ở Lab 1 → gửi lúc import → Lab 2 mã hoá lại | `export_db_passwords.py` + `DB_PASSWORDS_FILE` |
| User (+ role) | Copy dòng, giữ hash, map role theo tên | `sync_users.py` |
| Trạng thái xuất bản dashboard | Copy cờ theo UUID | `sync_dashboard_published.py` |
| Lịch sử query + saved query | Copy dòng, map user/connection | `sync_query_history.py` |
| Role tự tạo + quyền | `fab export-roles` / `import-roles` | **Đã thử: chỉ đúng với quyền không chứa ID.** Quyền vào dataset/database (`[db].[table](id:N)`) bị **lệch ID**, role vẫn không cấp được quyền (Phần V, bẫy #18) |
| Data thật | Không chuyển | — |
| Tab SQL Lab đang mở, log, alert/report | Không chuyển | — |

---

# Phần II. Môi trường lab

## 10. Kiến trúc

| Container | Vai trò | Truy cập |
|---|---|---|
| `superset_lab1` | Superset nguồn **2.1.1**, metadata ở `mysql_lab1` (**MySQL**) | http://localhost:8088 |
| `superset_lab2` | Superset đích **5.0.0**, metadata ở `postgres_lab2` (**Postgres**) | http://localhost:8089 |
| `mysql_lab1` | Metadata Lab 1 (`superset_meta`, MySQL) + data `sales`, `crm` | localhost:3307 |
| `postgres_lab1` | Data `finance`, `warehouse`, `marketing` (không phải metadata) | localhost:5433 |
| `postgres_lab2` | Metadata Lab 2 (`superset_meta`, **Postgres**) | localhost:5434 |

Cả hai Superset kết nối tới **cùng** `mysql_lab1` và `postgres_lab1` để đọc data thật. `postgres_lab2` chỉ chứa metadata của Lab 2, không liên quan tới `postgres_lab1`.

## 11. Tài khoản

| | user / password |
|---|---|
| Admin (cả 2 lab) | `admin` / `admin` |
| User Lab 1 | `zds_alice`, `zds_frank` (Alpha), `zds_bob`, `zds_carol`, `zds_emma`, `zds_grace` (Gamma), `zds_david` (sql_lab), `zds_henry` (Admin), mật khẩu `Passw0rd!` |
| User có sẵn Lab 2 | `lab2_nam` (Alpha), `lab2_linh` (Gamma), `lab2_hung` (Admin), mật khẩu `Lab2Passw0rd!` |
| MySQL root | `root` / `root` |
| Metadata DB | `superset` / `superset` |
| Read-only vào data | `reader` / `reader_pwd` |

## 12. Dữ liệu mẫu (trạng thái trước merge)

| | Lab 1 | Lab 2 |
|---|---|---|
| User | 9 (`admin` + 8 `zds_*`) | 4 (`admin`, `lab2_nam`, `lab2_linh`, `lab2_hung`) |
| Connection | 5 (2 MySQL: `MySQL - Sales`, `MySQL - CRM`; 3 Postgres: `Postgres - Finance`, `- Warehouse`, `- Marketing`) | 2 (`Lab2 - Legacy Sales`, `Lab2 - Legacy Finance`) |
| Dataset | 10 | 2 |
| Chart | 11 | 2 |
| Dashboard | 3 (`Sales Overview`, `Finance KPIs`, `Marketing Funnel`) | 1 (`Lab2 Legacy Dashboard`) |
| Lịch sử query | 11 (10 thành công, 1 lỗi cố ý) | 3 |
| Saved query | 3 | 1 |

Sau merge Lab 2 có: 12 user, 7 connection, 12 dataset, 13 chart, 4 dashboard, 14 dòng lịch sử, 4 saved query.

Data thật: MySQL `sales` (`orders` 3000 dòng, `order_items` 8000), `crm` (`customers` 300, `tickets` 1200); Postgres `finance` (`invoices` 2000, `payments` 1500), `warehouse` (schema `dw`: `fact_revenue` 5000, `dim_product` 50), `marketing` (`campaigns` 40, `ad_clicks` 10000).

## 13. Chi tiết Docker cần biết

- **Hai version khác nhau.** Biến `SUPERSET_VERSION_LAB1` (mặc định 2.1.1) và `SUPERSET_VERSION_LAB2` (mặc định 5.0.0) trong `docker-compose.yml`. Mỗi service có khối `build`/`image` riêng.
- **Image 2.1.1 chỉ có bản amd64.** Trên máy Apple Silicon (arm64) nó chạy giả lập, khởi động chậm hơn (lần đầu vài phút). Compose đã đặt `platform: linux/amd64` cho `superset_lab1`.
- **Cài driver DB, khác nhau giữa hai version** (`docker/Dockerfile` tự nhận biết):
  - 2.1.1 dùng Python hệ thống (3.8) và đã có sẵn `mysqlclient`, `psycopg2` → bỏ qua bước cài.
  - 5.0.0 dùng môi trường ảo `/app/.venv` (Python 3.10) và chưa có driver → phải cài bằng `uv pip install --python <python>`. Dùng `pip` thường sẽ cài nhầm vào Python hệ thống, không vào venv.
  - Cần `mysqlclient` (module `MySQLdb`), không chỉ PyMySQL, vì engine spec MySQL của Superset `import MySQLdb` trực tiếp. Thiếu thì chart MySQL báo `No module named 'MySQLdb'`.
- **Collation MySQL 8.** Không ép `utf8mb4_unicode_ci`; dùng mặc định của MySQL 8 (xem Phần V, bẫy #2).
- **Cookie riêng cho từng lab.** `superset_config.py` đặt `SESSION_COOKIE_NAME` theo tên lab, vì trình duyệt gắn cookie theo host (không theo port), hai lab trên `localhost` sẽ đè phiên của nhau.
- **`bootstrap.sh`** mỗi lần container khởi động: `superset db upgrade` → tạo admin (bỏ qua nếu đã có) → `superset init` → chạy `gunicorn`.
- **Healthcheck.** Postgres kiểm tra qua TCP (`-h 127.0.0.1`) để chỉ báo healthy sau khi các script init chạy xong; Superset dùng healthcheck có sẵn của image (`/health`).
- Thư mục `./backup` trên máy được mount vào `/backup` của `mysql_lab1` và `postgres_lab2`.

## 14. Dựng môi trường

```bash
docker compose up -d --build            # lần đầu build ~vài phút
docker compose ps                       # chờ cả 5 container "healthy"

docker exec superset_lab1 python /app/fake_data/seed_fake_metadata.py     # metadata Lab 1
docker exec superset_lab2 python /app/fake_data/seed_lab2_existing.py     # metadata riêng của Lab 2
docker exec superset_lab1 python /app/fake_data/seed_query_history.py     # lịch sử query thật, Lab 1
docker exec superset_lab2 python /app/fake_data/seed_query_history.py lab2

# kiểm tra Lab 1 hoạt động
docker exec superset_lab1 python /app/fake_data/smoke_test_api.py http://localhost:8088 zds_henry 'Passw0rd!'
```

`seed_fake_metadata.py` **chèn thẳng vào bảng metadata** (không qua giao diện), dùng SQLAlchemy reflection để thích ứng schema từng version (chỉ chèn cột có thật, tự điền cột NOT NULL thiếu). `seed_query_history.py` thì chạy query thật qua SQL Lab REST API để bảng `query` có dữ liệu thật.

---

# Phần III. Các bước thực hiện (runbook)

Chạy từ thư mục gốc của repo. Lab 2 **không cần dừng** trong suốt quá trình. Muốn chạy tự động toàn bộ: `./scripts/merge_lab1_to_lab2.sh`. Các bước dưới đây là bản làm tay, cùng thứ tự với script.

```
0 Xem trạng thái ─► 1 Backup Lab 2 ─► 2 Export từ Lab 1 ─► 2b Role tự tạo (nếu có) ─► 3 Thêm user
                                                             │
   8 Kiểm chứng ◄─ 7 db upgrade+init+restart ◄─ 6 Query history ◄─ 5 Cờ published ◄─ 4 Import (+mật khẩu)
```

**Thứ tự có ý nghĩa:** role tự tạo (2b) phải có trước user (3) vì `sync_users.py` gán role theo tên và không tạo role; user (3) phải có trước query history (6) vì cần map người chạy; connection (4) phải có trước query history (6) vì cần map theo tên connection.

### Bước 0. Xem trạng thái trước khi merge

```bash
docker exec postgres_lab2 psql -U superset -d superset_meta -c "
  SELECT 'users', COUNT(*) FROM ab_user UNION ALL SELECT 'connections', COUNT(*) FROM dbs
  UNION ALL SELECT 'datasets', COUNT(*) FROM tables UNION ALL SELECT 'charts', COUNT(*) FROM slices
  UNION ALL SELECT 'dashboards', COUNT(*) FROM dashboards;"
```

Kết quả mong đợi ở lab: `4, 2, 2, 2, 1` (thêm `query` = 3 và `saved_query` = 1).

### Bước 1. Backup Lab 2 (bước quan trọng nhất)

Đang ghi vào hệ thống có dữ liệu thật, nên backup trước để có đường lùi. Lab 2 là **Postgres** nên dùng `pg_dump` (không phải `mysqldump`):

```bash
docker exec postgres_lab2 sh -c \
  "pg_dump -U postgres --no-owner superset_meta > /backup/lab2_before_merge.sql"

# lưu danh sách những gì Lab 2 đang có, để bước kiểm chứng biết cái gì "không được mất"
docker exec superset_lab2 python /app/fake_data/verify_merge.py snapshot 2>/dev/null > backup/lab2_before.json
```

`--no-owner` bỏ các câu `ALTER ... OWNER TO` (owner gốc là superuser `postgres` bên trong container, phục hồi lại nên để owner là `superset` như lúc tạo DB). File dump nằm trong `./backup` trên máy (do mount).

### Bước 2. Export từ Lab 1

```bash
docker exec superset_lab1 superset export-datasources -f /tmp/datasources.zip
docker exec superset_lab1 superset export-dashboards  -f /tmp/dashboards.zip

docker cp superset_lab1:/tmp/datasources.zip backup/
docker cp superset_lab1:/tmp/dashboards.zip  backup/

ls -l backup/                            # thấy 2 file zip
unzip -l backup/dashboards.zip           # xem danh sách file YAML bên trong
unzip -p backup/dashboards.zip '*/databases/MySQL_-_Sales.yaml'   # đọc thử 1 file
```

Bước này chỉ đọc, Lab 1 không bị ảnh hưởng. **Chú ý đường dẫn:** viết `backup/` (không có `/` đứng đầu). `/backup` là thư mục ở gốc ổ đĩa máy Mac, chỉ đọc, sẽ báo `read-only file system`. (`/backup` chỉ đúng khi ở *bên trong container `mysql_lab1` hoặc `postgres_lab2`*, hai container duy nhất có mount này.) Đường đi của file: trong `/tmp` của container Lab 1 → `docker cp` ra `./backup` trên máy → `docker cp` vào `/tmp` của container Lab 2. Không có volume nào tham gia; `./backup` là nơi giữ lâu dài.

### Bước 2b. Role tự tạo (nếu có), làm TRƯỚC Bước 3

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

**Giới hạn:** lệnh này chỉ chuyển được quyền **không chứa ID** (ví dụ `can_read on Dashboard`). Quyền vào từng dataset/database (`[db].[table](id:N)`) bị lệch ID (bẫy #18). Dataset chỉ tồn tại ở Lab 2 sau Bước 4, nên các quyền này phải được **cấp lại sau Bước 4 và Bước 7 (`superset init`)**, bằng tay hoặc script (chưa có). Kiểm tra role đã có: `SELECT name FROM ab_role;` trên metadata Lab 2. Nếu Lab 1 đã **tự thêm quyền vào role mặc định** (ví dụ vào Gamma), phần đó cũng không tự chuyển: so sánh và bổ sung tay.

### Bước 3. Thêm user của Lab 1 vào Lab 2

```bash
docker exec superset_lab2 python /app/fake_data/sync_users.py
```

Mong đợi: `added 8 ...` và `skipped 1 (already in target): admin`.
- Khớp theo `username`; user đã có ở Lab 2 **không bị sửa**.
- Chép nguyên chuỗi hash mật khẩu (mục 4.2).
- Role gán theo **tên role**; role không tồn tại ở Lab 2 sẽ in cảnh báo.
- Nguồn đọc từ biến `SRC_META_URI` (mặc định trỏ tới metadata `mysql_lab1`).
- **Chỉ ghi vào 2 bảng: `ab_user` và `ab_user_role`** (đã đo: +8 dòng mỗi bảng). Không tạo role, không ghi `ab_permission*` (danh mục quyền do Superset tự tạo) và không chép quyền gắn vào role (`ab_permission_view_role`, bẫy #18).
- User đã tồn tại ở Lab 2 bị bỏ qua hoàn toàn (kể cả role); so sánh role từng user giữa hai Lab bằng SQL trực tiếp (câu lệnh ở PRODUCTION_RUNBOOK mục 7.4) để biết ai cần sửa tay.

### Bước 4. Import connection, dataset, chart, dashboard vào Lab 2

Vì file export không có mật khẩu (mục 6), cần cung cấp lúc import. Với nhiều connection, dùng file JSON lấy tự động từ Lab 1:

```bash
# 4a. Xuất mật khẩu mọi connection ở Lab 1 ra JSON {"tên connection": "mật khẩu"}
docker exec superset_lab1 python /app/fake_data/export_db_passwords.py /tmp/passwords.json

# 4b. Chuyển thẳng container → container (không qua ổ đĩa máy), cho Lab 2 quyền đọc
docker cp superset_lab1:/tmp/passwords.json - | docker cp - superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/passwords.json

# 4c. Import, mỗi connection lấy đúng mật khẩu của nó
docker cp fake_data/import_bundle_direct.py superset_lab2:/tmp/
docker exec -u root superset_lab2 chown superset /tmp/import_bundle_direct.py
docker cp backup/datasources.zip     superset_lab2:/tmp/
docker cp backup/dashboards.zip      superset_lab2:/tmp/
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json superset_lab2 python /tmp/import_bundle_direct.py dataset   /tmp/datasources.zip admin
docker exec -e DB_PASSWORDS_FILE=/tmp/passwords.json superset_lab2 python /tmp/import_bundle_direct.py dashboard /tmp/dashboards.zip admin

# 4d. XOÁ file mật khẩu ngay (chữ thường)
docker exec superset_lab1 rm -f /tmp/passwords.json
docker exec superset_lab2 rm -f /tmp/passwords.json
```

Mỗi lệnh import phải in `... import (direct): OK, N connection(s) in bundle`. Script chạy Superset import **ngay trong container** (không đăng nhập, không HTTP); tham số cuối (`admin`) là user đã tồn tại làm owner.
- Ghi ra file (không dùng stdout) vì Superset in log ra stdout và làm hỏng JSON.
- `chown superset` là bắt buộc: `docker cp` giữ quyền `600` của người tạo, nên không có nó thì báo `Permission denied`.
- Object của Lab 1 được **thêm mới** vào Lab 2 với ID mới. Object cũ của Lab 2 **không bị xoá hay sửa**. Object đã từng import (cùng UUID) bị ghi đè bằng bản Lab 1, nên chạy lại không tạo trùng.
- Muốn dùng mật khẩu gõ tay cho vài connection: `-e DB_PASSWORDS_JSON='{"MySQL - Sales":"pwd1"}'`; connection không có trong danh sách rơi về `DB_PASSWORD`.

### Bước 5. Khôi phục trạng thái xuất bản của dashboard

```bash
docker exec superset_lab2 python /app/fake_data/sync_dashboard_published.py
```

Mong đợi: `dashboards: 3 updated`. Xem lý do ở Phần V (bẫy #1).

### Bước 6. Copy lịch sử query và saved query

```bash
docker exec superset_lab2 python /app/fake_data/sync_query_history.py
```

Mong đợi: `query added 11` và `saved_query added 3`. Chạy lại lần hai: `added 0, skipped ...` (không trùng).

### Bước 7. `db upgrade`, `init`, restart Lab 2

```bash
docker exec superset_lab2 superset db upgrade   # no-op nếu schema đã ở head
docker exec superset_lab2 superset init         # tạo permission cho connection/dataset mới
docker compose restart superset_lab2
docker compose ps superset_lab2                 # chờ "healthy"
```

### Bước 8. Kiểm chứng

```bash
./scripts/verify.sh
```

Xem chi tiết ở Phần IV. Kết quả mong đợi: `MERGE OK` và `ALL CHECKS PASSED`.


### Tự động hoá

`scripts/merge_lab1_to_lab2.sh` chạy Bước 1 → 7 (kể cả tự lấy mật khẩu, xoá file mật khẩu, backup Lab 2 và lưu snapshot). Nó ghi file rollback `backup/lab2_before_merge_<timestamp>.sql`.

---

# Phần IV. Kiểm chứng, rollback, reset

## 15. Kiểm chứng (`scripts/verify.sh`)

Ba nhóm kiểm tra:

1. **So sánh tên object** (`fake_data/verify_merge.py check`): mọi user, connection, dataset, chart, dashboard, *trạng thái dashboard*, lịch sử query, saved query của Lab 1 đã có ở Lab 2 **và** không thứ gì Lab 2 từng có bị mất (so với `backup/lab2_before.json`). In bảng:

   ```
                  lab1  lab2 before  lab2 now   lab1 missing in lab2 | lab2-before lost
   users             9            4        12   0 | 0
   connections       5            2         7   0 | 0
   ...
   MERGE OK
   ```

2. **Test từng connection** (`check_connections.py`): giải mã mật khẩu bằng `SECRET_KEY` của Lab 2 và mở kết nối. Phải thấy `connect OK` cho cả 7 connection.

3. **Chạy toàn bộ chart** (`smoke_test_api.py`) bằng tài khoản đã migrate (`zds_alice`) và đăng nhập thử tài khoản cũ của Lab 2 (`lab2_nam`). Phải thấy đủ 13 chart ra số liệu và **4 dashboard** (không phải 1).

Kiểm tra bằng mắt: mở http://localhost:8089, đăng nhập `zds_alice` / `Passw0rd!`, xem đủ 4 dashboard, 7 connection; SQL Lab → Query History thấy 14 dòng.

## 16. Rollback

Nếu merge làm hỏng Lab 2, khôi phục từ bản backup ở Bước 1:

```bash
docker compose stop superset_lab2
docker exec postgres_lab2 dropdb -U postgres superset_meta
docker exec postgres_lab2 createdb -U postgres -O superset superset_meta
docker exec postgres_lab2 sh -c "psql -U postgres -d superset_meta -f /backup/lab2_before_merge.sql"
docker compose start superset_lab2
```

Việc này **không ảnh hưởng data thật và không ảnh hưởng Lab 1** (Lab 1 chỉ bị đọc), nên người dùng có thể quay lại dùng Lab 1 ngay.

## 17. Reset để làm lại (chỉ dành cho lab)

```bash
./scripts/reset_lab2.sh          # đưa Lab 2 về "trước merge": metadata trống rồi seed dữ liệu riêng; Lab 1 giữ nguyên
docker compose down -v           # xoá sạch mọi thứ, dựng lại từ đầu
```

`reset_lab2.sh` dừng Lab 2, drop và tạo lại `superset_meta`, khởi động lại (bootstrap tạo schema và admin), seed lại dữ liệu riêng của Lab 2 và **xoá nội dung `./backup`** (kể cả file mật khẩu nếu còn sót).

---

# Phần V. Bẫy và bài học đã gặp

Những vấn đề này gặp thật khi làm lab; nhiều cái sẽ gặp lại ở production.

| # | Vấn đề | Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|---|---|
| 1 | **Dashboard mất trạng thái xuất bản** khi import từ 2.1.1 | Admin thấy 4 dashboard, user Alpha/Gamma chỉ thấy 1 (`published=0`) | Export của Superset **2.1.x không chứa** trường `published`; 5.0.0 mặc định chưa xuất bản. User thường chỉ thấy dashboard đã xuất bản hoặc do mình sở hữu | `sync_dashboard_published.py` chép cờ theo UUID. **Bài học:** export từ bản cũ có thể thiếu trường; so sánh vài object quan trọng sau khi nạp |
| 2 | **Lỗi collation MySQL 8** làm API danh sách chết với user bị lọc theo quyền | `422 Illegal mix of collations (utf8mb4_bin,NONE) and (binary,IGNORABLE)`; trang Database Connections **trống** | Cột tạo với `utf8mb4_unicode_ci` không khớp collation mặc định của kết nối MySQL 8 (`utf8mb4_0900_ai_ci`). Chỉ lộ với user đi qua câu query lọc theo quyền datasource (Gamma/sql_lab trong lab); admin và Alpha (có toàn quyền datasource) không đi qua câu đó nên không thấy lỗi. Đã tái hiện bằng câu SQL riêng: cột `unicode_ci` lỗi, cột dùng collation mặc định thì không | Dùng collation mặc định của MySQL 8 cho metadata DB (đã bỏ `--collation-server`). **Nếu metadata DB thật có collation khác**, kiểm tra bằng cách đăng nhập user không-admin |
| 3 | **Trang Connection trống** dù dữ liệu còn | Danh sách trống với một số user | Role Gamma / sql_lab **không có quyền** xem connection (đúng theo thiết kế); cộng với cookie dùng chung giữa hai lab | Đăng nhập admin để kiểm tra; đặt cookie riêng cho từng lab |
| 4 | **Cookie dùng chung giữa hai lab** | Đăng nhập Lab 2 làm Lab 1 "đổi user" | Cookie gắn theo host, không theo port; hai lab cùng `localhost` cùng `SECRET_KEY` | `SESSION_COOKIE_NAME` riêng cho mỗi lab; xoá cookie `localhost` nếu thấy lạ |
| 5 | **CLI import bị từ chối** | `CommandInvalidError` khi `superset import-dashboards` | ZIP không có mật khẩu connection; CLI không cho truyền | Import trực tiếp trong tiến trình kèm `passwords` (`import_bundle_direct.py`) |
| 6 | **Thiếu driver MySQL** | Chart MySQL: `No module named 'MySQLdb'` | Engine spec MySQL `import MySQLdb`; image mỏng không có; PyMySQL không đủ | Cài `mysqlclient` |
| 7 | **`pip install` không vào venv của 5.0.0** | Cài xong vẫn `No module named psycopg2` | 5.0.0 dùng `/app/.venv`; `pip` của hệ thống cài sang Python khác | Dùng `uv pip install --python <python trong venv>` |
| 8 | **Import báo `offset: Field may not be null`** | `HTTP 500`/validate fail khi import dataset | Cột `tables.offset` bị để NULL (do script seed chèn thẳng); Superset thật luôn ghi 0 | Sửa seed (`offset=0`). **Ở production:** nếu dữ liệu cũ có `offset` NULL sẽ gặp lại; cập nhật `UPDATE tables SET offset=0 WHERE offset IS NULL` |
| 9 | **Mật khẩu connection sai / thiếu** | Import báo `HTTP 500`, log `password authentication failed` (5.0.0); hoặc connection `FAIL` sau khi nạp | Connection không có trong file mật khẩu rơi về mật khẩu mặc định `DB_PASSWORD` | 5.0.0 từ chối ngay khi nạp dataset vì kết nối thử; với version khác chưa biết, nên luôn chạy `verify.sh`. Chú ý dòng `note: no specific password...` |
| 10 | **`docker cp` vào `/backup` báo `read-only file system`** | `openat backup: read-only file system` | Đích là `/backup` (gốc ổ đĩa Mac) thay vì `backup/` | Dùng `backup/` không có `/` đầu |
| 11 | **`Permission denied` khi đọc `passwords.json`** trong container | Lỗi mở file | `docker cp` giữ quyền `600` của người tạo (uid máy Mac) | `docker exec -u root superset_lab2 chown superset /tmp/passwords.json` |
| 12 | **`passwords.json` bị lẫn log** | `JSONDecodeError` | Superset in log ra stdout, lẫn vào chuyển hướng `> file` | Script ghi thẳng ra file bằng tham số, không qua stdout |
| 13 | **SQL Lab 2.1.1 không tự áp schema Postgres** | Query `FROM fact_revenue` lỗi `relation does not exist` | 2.1.1 không đặt `search_path` theo schema đã chọn | Ghi rõ schema (`dw.fact_revenue`). Lịch sử đã copy chỉ là nhật ký; chạy lại trên 5.0.0 có thể khác kết quả |
| 14 | **User Alpha không chạy được SQL Lab qua API** | `403` khi execute | Trong lab, Alpha bị từ chối (Admin chạy được); role `sql_lab` cũng không gọi được API đăng nhập/CSRF trong lab | Chỉ ảnh hưởng dữ liệu seed lab (lịch sử query chỉ có `admin`, `zds_henry`) |
| 15 | **`sql` là từ khoá MySQL nhưng không phải ở Postgres** | Lỗi cú pháp khi `SELECT ... sql ...` trên MySQL; backtick lại lỗi cú pháp trên Postgres | `sql` là reserved word ở MySQL, không phải ở Postgres; hai dialect dùng ký tự quote khác nhau (backtick vs `"`) | Không hardcode một kiểu quote: chọn ký tự theo `engine.dialect.name` lúc chạy (`verify_merge.py` làm vậy vì Lab 1 là MySQL, Lab 2 là Postgres) |
| 16 | **Postgres báo healthy quá sớm** | Superset khởi động khi DB chưa sẵn sàng | Lúc chạy init script, server tạm chỉ nghe unix socket | Healthcheck qua TCP (`pg_isready -h 127.0.0.1`) |
| 17 | **Warning `Cannot drop column 'druid_datasource_id'`** khi `db upgrade` trên MySQL | Log cảnh báo (không dừng) | Cảnh báo đã biết của migration Superset | Bỏ qua được |
| 18 | **Role mất quyền vào dataset/database** | Sau merge, user Gamma/role tự tạo thấy **0 dataset, 0 dashboard** dù Lab 1 thấy đủ (đã thử: `zds_bob` 2 dataset → 0) | Quyền theo đối tượng gắn với role (`datasource_access` trên `[db].[table](id:N)`) **không nằm trong export/import**. `fab export-roles/import-roles` chép tên quyền kèm **ID cũ**, mà ID ở Lab 2 khác nên quyền trỏ vào đối tượng không tồn tại | Tạo lại quyền cho role ở Lab 2, hoặc viết script ánh xạ ID theo UUID (chưa có). **Kiểm tra bằng user Gamma thật ngay sau khi nạp.** Cảnh giác quyền rơi nhầm nếu trùng tên connection và ID |
| 19 | **Owner bị đổi thành người import** | Dashboard của user A hiện owner `admin`; user Alpha **không sửa được** dashboard của chính mình (đã thử: david, alice, frank → admin) | Import gán owner là user chạy import; owner nằm ở các bảng nối `dashboard_user`, `slice_user`, `sqlatable_user` không đi theo | Map owner theo `username` (chưa có script) hoặc chấp nhận và thông báo; tạm thời admin sửa hộ |
| 20 | **Role mặc định của hai version có bộ quyền khác nhau** | Không lỗi ngay; quyền mà admin tự thêm vào Gamma/Alpha ở Lab 1 **không có** ở Lab 2 | Đo ở lab (nguyên bản): 2.1.1 có Admin 204, Alpha 129, Gamma 101, sql_lab 27; 5.0.0 có Admin 161, Alpha 99, Gamma 74, sql_lab 25 (5.0.0 đã bỏ/đổi tên nhiều quyền cũ). `sync_users.py` gán role mặc định theo tên nên dùng luôn bộ quyền của Lab 2 | So danh sách quyền Gamma/Alpha/sql_lab giữa hai Lab; bổ sung tay **chỉ** quyền tuỳ chỉnh cần giữ. **Không** chép cả bộ quyền của Lab 1 sang (xem #21) |
| 21 | **`fab import-roles` nguyên file làm phình quyền role mặc định** | Sau import, Gamma ở Lab 2 từ 74 lên 117 quyền (Admin +67, Alpha +47, sql_lab +5) | File export chứa cả role mặc định của 2.1.1 và `import-roles` **cộng thêm** các quyền cũ vào role cùng tên ở Lab 2 (đã đo: +43 quyền 2.x cho Gamma, không bớt quyền nào) | Chỉ import role tự tạo: lọc file trước (Bước 2b) |
| 22 | **So sánh `uuid` giữa MySQL và Postgres luôn sai** (không báo lỗi) | `sync_dashboard_published.py`/`sync_query_history.py` không nhận ra dòng đã tồn tại (không dedupe được) hoặc bỏ sót toàn bộ dòng cần đồng bộ | Superset lưu cột `uuid` dạng `BINARY(16)` (bytes) trên MySQL nhưng dạng `UUID` gốc (chuỗi) trên Postgres qua SQLAlchemy reflection; so `bytes == str` không bao giờ `True` | Chuẩn hoá về `str(uuid.UUID(bytes=v)) if isinstance(v, bytes) else str(v)` trước khi so khớp; khi ghi vào cột đích phải chuyển ngược lại đúng kiểu cột đích cần (`.bytes` nếu không phải native UUID) |
| 23 | **`COALESCE(cot_boolean, 0)` lỗi trên Postgres** | `DatatypeMismatch: COALESCE types boolean and integer cannot be matched` | MySQL không có kiểu boolean thật (chỉ là `TINYINT`) nên trộn với số nguyên vẫn chạy; Postgres có kiểu `boolean` thật, không tự ép sang `integer` | Dùng `COALESCE(cot, false)`; nếu cần in ra text giống nhau ở cả hai dialect (ví dụ để so sánh chuỗi), bọc thêm `CASE WHEN ... THEN 1 ELSE 0 END` vì Postgres nối chuỗi ra `true`/`false` còn MySQL ra `1`/`0` |
| 24 | **Sequence của bảng phụ trợ FAB không tự sinh khoá chính trên Postgres** | Insert vào bảng như `ab_user_role` thiếu giá trị khoá chính | Cột tự tăng của một số bảng liên kết (association table) không được SQLAlchemy nhận diện là có `server_default` khi reflect từ Postgres | Gọi thủ công `pg_get_serial_sequence()` + `nextval()` trước khi insert nếu bảng đó không tự cấp ID (xem `seed_fake_metadata.py::insert()`) |

### Các điểm khác cần nhớ

- **Trùng tên connection nhưng khác UUID** → import báo lỗi. Rà và đổi tên một bên trước.
- **Hostname trong connection.** Trong lab hai lab cùng trỏ vào data server nên connection không phải đổi host. Nếu Lab 2 phải kết nối tới host khác Lab 1, phải sửa `sqlalchemy_uri` (trong file YAML hoặc sau khi import). Đây là một thao tác `UPDATE dbs SET sqlalchemy_uri = REPLACE(...)` trong phương án dump/restore.
- **Owner** của chart/dashboard/dataset bị đổi thành người import (mục 7); hậu quả cụ thể ở bẫy #19.
- **Quyền của role vào dataset/database không đi theo** (bẫy #18) và **RLS** không nằm trong export/import.
- **Chỉ migrate lên cùng version hoặc mới hơn** (mục 5).
- **Chạy lại an toàn** nhờ UUID / `username` / `client_id`: tất cả script đều idempotent (đã thử chạy 2 lần: lần 2 `added 0`).

---

# Phần VI. Áp dụng cho production

## 18. Khác biệt giữa lab và production

| | Lab | Production |
|---|---|---|
| Xác thực | Tài khoản trong DB (`admin`/`admin`) | Có thể LDAP/SSO; script mặc định đăng nhập `admin`/`admin` phải đổi user/mật khẩu thật hoặc dùng token |
| Mật khẩu connection | Một tài khoản `reader` chung | Mỗi connection một mật khẩu riêng (ví dụ 43 cái) |
| `SECRET_KEY` | Đặt sẵn trong compose | Do người dựng Lab 1 đặt; chạy script *bên trong* container/máy Lab 1 để dùng đúng key |
| Data host | Cùng `mysql_lab1`/`postgres_lab1` | Kiểm tra Lab 2 có truy cập tới cùng host data không |
| Quy mô | 5 connection, 11 chart | Nhiều hơn nhiều; thời gian chưa đo |
| Role | Chỉ role mặc định | Có thể có role tự tạo |
| Metadata DB collation | Mặc định MySQL 8 | Có thể khác; xem bẫy #2 |

## 19. Checklist

**Trước ngày làm**
- [ ] Xác nhận version hai bên (`superset version`); Lab 2 phải bằng hoặc mới hơn Lab 1.
- [ ] Liệt kê connection, đối chiếu tên hai bên để tránh trùng tên khác UUID.
- [ ] Có đủ mật khẩu connection (hoặc quyền chạy `export_db_passwords.py`) và biết `SECRET_KEY`/đúng máy để chạy.
- [ ] Liệt kê role tự tạo ở Lab 1 (nếu có).
- [ ] Biết cách đăng nhập (local hay LDAP/SSO) để chọn user chạy import.
- [ ] Chốt các quyết định: giữ owner gốc không? tắt Lab 1 lúc nào? khung giờ làm?
- [ ] Thử toàn bộ quy trình trên **bản sao** của hệ thống thật trước; đo thời gian.

**Khi làm**
- [ ] Backup metadata Lab 2 (Bước 1), lưu snapshot danh sách.
- [ ] Thực hiện Bước 2 → 7; ở mỗi bước đối chiếu kết quả mong đợi.
- [ ] Xoá `passwords.json` ngay sau khi import.
- [ ] Ngoài giờ cao điểm, vì Lab 2 restart một lần.

**Sau khi làm**
- [ ] `verify.sh` báo `MERGE OK`, mọi connection `connect OK`.
- [ ] Mở các dashboard quan trọng bằng vài user thuộc nhiều role khác nhau (Admin, Alpha, Gamma).
- [ ] So sánh vài dashboard/chart/dataset quan trọng giữa hai bên (tìm trường bị mất như bẫy #1).
- [ ] Người dùng thử đăng nhập.
- [ ] Giữ Lab 1 chạy một thời gian rồi mới tắt.

## 20. Bảo mật khi thao tác

- `passwords.json` là mật khẩu chữ thường: chỉ tạo trong container, chuyển container → container, **xoá ngay**, không để trên máy, không commit git.
- Đừng gõ mật khẩu thật thẳng vào terminal (lưu trong lịch sử lệnh). Dùng file hoặc `-e DB_PASSWORDS_JSON="$(cat file.json)"`.
- `SECRET_KEY` cần giữ kín như mật khẩu; ai có `SECRET_KEY` + metadata DB thì lấy được mật khẩu connection.
- Chỉ người có quyền quản trị mới được chạy `export_db_passwords.py`.

---

# Phần VII. Chưa kiểm chứng

- **Chưa chạy trên hệ thống thật** (zdslab1 / zdslab2); mọi kết quả ở đây là từ lab mô phỏng.
- **Quyền của role vào dataset/database ở Lab 2**: chưa có công cụ đúng (bẫy #18); cần script ánh xạ ID hoặc tạo lại tay.
- **Row Level Security**: chưa thử (lab không có dữ liệu RLS); biết chắc là không nằm trong export/import.
- **Alerts & Reports**: không thấy trên giao diện Lab 1 (tính năng tắt); chưa đếm được dữ liệu ẩn trong database thật.
- **Đăng nhập LDAP/SSO**: chưa thử; user loại này không có mật khẩu trong `ab_user`.
- **Thời gian thực hiện**: chưa đo trên dữ liệu thật.
- **Giữ owner gốc** của chart/dashboard/dataset: **chưa làm, và có hậu quả thật** (user Alpha mất quyền sửa object của mình, bẫy #19).
- **Chép nguyên giá trị mã hoá** của mật khẩu connection giữa hai lab (thay vì giải mã rồi mã hoá lại): chưa kiểm chứng giữa 2.1.1 và 5.0.0; cách này cũng đòi hỏi hai lab **chung `SECRET_KEY`**.
- **Hash mật khẩu chiều ngược** (bản mới sang bản cũ): chưa thử.
- **Trường khác bị mất** giữa các version ngoài `published`: mới biết một trường; cần so sánh thêm ở dữ liệu thật.
- **Tab SQL Lab đang mở, log, alert/report**: không migrate.

---

# Phụ lục A. Bản đồ repo

```
docker-compose.yml                  5 container: 2 Superset, mysql_lab1, postgres_lab1, postgres_lab2
docker/Dockerfile                   apache/superset:<version> + driver (tự nhận biết 2.x / 5.x)
superset/superset_config.py         đọc META_DB_URI, SUPERSET_SECRET_KEY từ env; cookie riêng mỗi lab
superset/bootstrap.sh               db upgrade → create-admin → init → gunicorn
initdb/mysql/00_superset_meta.sql          tạo DB metadata (MySQL) + user superset, cho mysql_lab1
initdb/mysql/10_lab1_data.sql              data thật sales, crm + user reader (chỉ mysql_lab1)
initdb/postgres/00_superset_meta_lab2.sql  tạo DB metadata (Postgres) + user superset, cho postgres_lab2
initdb/postgres/10_lab1_data.sql           data thật finance, warehouse, marketing + role reader
backup/                             nơi chứa export ZIP, backup, snapshot (mount vào /backup của mysql_lab1 và postgres_lab2)
```

| Script | Chạy ở | Làm gì |
|---|---|---|
| `fake_data/seed_fake_metadata.py` | Lab 1 | Chèn thẳng user, connection, dataset, chart, dashboard vào metadata (lab) |
| `fake_data/seed_lab2_existing.py` | Lab 2 | Tạo dữ liệu **riêng** của Lab 2 để thử merge vào hệ thống không trống |
| `fake_data/seed_query_history.py` | Lab 1 / Lab 2 (`lab2`) | Chạy query thật qua SQL Lab API + tạo saved query |
| `fake_data/smoke_test_api.py` | Cả hai | Đăng nhập qua API, đếm object, chạy mọi chart |
| `fake_data/check_connections.py` | Lab 2 | Mở thử từng connection (giải mã mật khẩu bằng `SECRET_KEY`) |
| `fake_data/export_db_passwords.py` | Lab 1 | Xuất `{tên connection: mật khẩu}` ra JSON, dùng `d.password` tự giải mã |
| `fake_data/import_bundle_direct.py` | Lab 2 | Import ZIP **trực tiếp trong ứng dụng** (không đăng nhập, không HTTP) kèm mật khẩu từng connection. Cách duy nhất dùng trong repo này |
| `fake_data/sync_users.py` | Lab 2 | Thêm user Lab 1 (theo `username`), giữ hash, gán role theo tên |
| `fake_data/sync_dashboard_published.py` | Lab 2 | Chép cờ `published` theo UUID |
| `fake_data/sync_query_history.py` | Lab 2 | Copy lịch sử query + saved query, map user/connection |
| `fake_data/verify_merge.py` | Lab 2 | `snapshot` (trước) và `check` (sau) so sánh theo tên |
| `scripts/merge_lab1_to_lab2.sh` | Máy host | Chạy tự động Bước 1 → 7 |
| `scripts/verify.sh` | Máy host | Bước 8: kiểm chứng đầy đủ |
| `scripts/reset_lab2.sh` | Máy host | Đưa Lab 2 về trạng thái trước merge |

Các script `sync_*` và `verify_merge` đọc metadata của Lab 1 qua biến `SRC_META_URI` (mặc định trỏ tới `mysql_lab1`); đổi biến này để dùng cho môi trường khác.

# Phụ lục B. FAQ (những câu đã hỏi trong quá trình làm)

**Vì sao chỉ có `datasources.zip` và `dashboards.zip`, không có file "datasets" hay "users"?**
`datasources.zip` **đã chứa** dataset *và* connection (Superset gọi cặp này là "datasources"). Còn user không có lệnh export, nên ta copy dòng (mục 7).

**"Import bundle" có nghĩa là gì?**
Nạp file ZIP export vào Superset đích. Điểm vướng là ZIP không có mật khẩu connection, nên phải kèm mật khẩu lúc nộp. `import_bundle_direct.py` gọi thẳng lệnh import của Superset trong tiến trình, kèm mật khẩu.

**`import_bundle_direct.py` có điền mật khẩu vào file ZIP không?**
Không. ZIP giữ nguyên. Mật khẩu đi ở phần riêng (tham số `passwords` truyền cho lệnh import), Lab 2 nhận rồi tự mã hoá và lưu vào metadata của nó.

**`DB_PASSWORD=reader_pwd` là gì?**
Chỉ là mật khẩu của tài khoản `reader` do lab tạo. Ở công ty phải dùng mật khẩu thật của từng connection (`DB_PASSWORDS_FILE`).

**Có 43 connection thì lấy mật khẩu thế nào?**
Chạy `export_db_passwords.py` trong container Lab 1: Superset tự giải mã. Hoặc lập file JSON từ kho mật khẩu công ty. Xem mục 6.3.

**Script `export_db_passwords.py` giải mã bằng cách nào?**
Không có bước giải mã tường minh. Dòng `d.password` (với `d` là một dòng của model `Database`) tự giải mã vì cột `password` được khai báo là kiểu mã hoá tự động dùng `SECRET_KEY` (mục 4.1). Script gọi `create_app()` để nạp `SECRET_KEY` của Lab 1.

**Mật khẩu user có bị giải mã khi migrate không?**
Không. Nó là hash một chiều; ta chép nguyên chuỗi hash, user đăng nhập bằng mật khẩu cũ vẫn được (mục 4.2).

**Muốn giữ bảo mật, chỉ giải mã khi chạy trong container thì sao?**
Quy trình hiện tại: `passwords.json` chỉ tạo trong container Lab 1, chuyển container → container (không qua ổ đĩa máy), và xoá ngay. Chặt hơn nữa: lấy mật khẩu từ kho bí mật của công ty (không giải mã ở đâu cả), hoặc chép nguyên giá trị mã hoá nếu hai lab chung `SECRET_KEY` (chưa kiểm chứng giữa hai version).

**Có mang được lịch sử query không?**
Có, phần nhật ký (ai, SQL gì, khi nào, thành công/lỗi) bằng `sync_query_history.py`. Không mang kết quả đã cache.

**Vì sao không dùng dump/restore?**
Vì nó ghi đè toàn bộ Lab 2 (mất dữ liệu riêng), và giữa hai version khác schema (2.1.1 → 5.0.0) nó kéo theo bước nâng schema nhiều bản lớn mà chưa được thử. Mục 8.

**Vì sao trang Database Connections trống?**
Thường do đăng nhập nhầm user (role Gamma/sql_lab không có quyền xem), do cookie dùng chung giữa hai lab, hoặc lỗi collation MySQL. Bẫy #2, #3, #4.

# Phụ lục C. Lệnh hữu ích

```bash
# version thật của từng lab
docker exec superset_lab1 python -c "import importlib.metadata as m; print(m.version('apache-superset'))"

# đếm object trong metadata Lab 1 (MySQL)
docker exec -e MYSQL_PWD=root mysql_lab1 mysql -uroot superset_meta -e "
  SELECT (SELECT COUNT(*) FROM ab_user) users, (SELECT COUNT(*) FROM dbs) conns,
         (SELECT COUNT(*) FROM tables) datasets, (SELECT COUNT(*) FROM slices) charts,
         (SELECT COUNT(*) FROM dashboards) dashboards,
         (SELECT COUNT(*) FROM query) history, (SELECT COUNT(*) FROM saved_query) saved;"

# cùng câu đếm nhưng cho metadata Lab 2 (Postgres)
docker exec postgres_lab2 psql -U superset -d superset_meta -c "
  SELECT (SELECT COUNT(*) FROM ab_user) users, (SELECT COUNT(*) FROM dbs) conns,
         (SELECT COUNT(*) FROM tables) datasets, (SELECT COUNT(*) FROM slices) charts,
         (SELECT COUNT(*) FROM dashboards) dashboards,
         (SELECT COUNT(*) FROM query) history, (SELECT COUNT(*) FROM saved_query) saved;"

# alembic head (phiên bản schema) - Lab 1 (MySQL) / Lab 2 (Postgres)
docker exec -e MYSQL_PWD=root mysql_lab1 mysql -uroot superset_meta -e "SELECT * FROM alembic_version;"
docker exec postgres_lab2 psql -U superset -d superset_meta -c "SELECT * FROM alembic_version;"

# dashboard đã xuất bản chưa (Lab 2)
docker exec postgres_lab2 psql -U superset -d superset_meta -c "SELECT id, dashboard_title, published FROM dashboards;"

# xem log nạp/import ở Lab 2
docker logs --since 10m superset_lab2 2>&1 | grep -iE "error|password authentication|traceback" | head

# xem nội dung trong file export mà không giải nén ra đĩa
unzip -l backup/dashboards.zip
unzip -p backup/dashboards.zip '*/databases/MySQL_-_Sales.yaml'
```
