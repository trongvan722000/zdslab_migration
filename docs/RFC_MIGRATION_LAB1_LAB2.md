# [RFC] Migrate metadata Superset: ZDS Lab 1 → ZDS Lab 2

## Executive Summary

**Mục tiêu:** Chuyển toàn bộ **metadata** (user, database connection, dataset, dashboard, chart, lịch sử SQL Lab) đang dùng ở ZDS Lab 1 (Superset 2.1.1) sang ZDS Lab 2 (Superset 5.0.0), mà **không xoá** những gì Lab 2 đang có sẵn.

**Giải pháp:** Không dump/restore đè nguyên database metadata (sẽ xoá sạch Lab 2 và có rủi ro không tương thích schema giữa hai version). Thay vào đó, **export/import theo từng loại object** bằng cơ chế UUID có sẵn của Superset, kết hợp 3 script đọc thẳng metadata Lab 1 và ghi thẳng vào metadata Lab 2 cho phần Superset không hỗ trợ export (user, role, lịch sử query).

**Kết quả kỳ vọng:** Lab 2 có đầy đủ connection/dataset/dashboard/user của Lab 1 **cộng thêm** vào những gì đang có; user cũ đăng nhập được ngay bằng đúng mật khẩu cũ; không có thời gian dừng dịch vụ (Lab 2 không cần tắt trong lúc migrate); có thể rollback về trước khi migrate nếu phát sinh lỗi.

## 1. Vấn đề

Lab 1 (Superset 2.1.1) là bản cũ, cấu hình lâu ngày phát sinh lỗi vặt, không còn được cập nhật. Công ty cần chuyển người dùng sang Lab 2 (Superset 5.0.0) — bản mới, ổn định hơn. Cái khó: Lab 2 **không phải môi trường trống** — đã có user, connection và dashboard riêng đang được một nhóm khác sử dụng, không được phép mất. Vì vậy đây không phải là "dựng Lab 2 rồi copy Lab 1 vào", mà là **gộp hai bộ metadata làm một**, không đụng tới phần đã có của Lab 2.

Ràng buộc thêm: đăng nhập cả hai Lab dùng LDAP + OTP (Google Authenticator) — không có sẵn mật khẩu tĩnh để tự động hoá bằng cách "login rồi thao tác qua giao diện/API"; và dữ liệu thật (các bảng trong MySQL/Postgres/StarRocks) không nằm trong phạm vi migrate — chỉ có metadata di chuyển, hai Lab tiếp tục cùng truy vấn vào các database thật đó.

## 2. Hiện trạng

| | ZDS Lab 1 (nguồn) | ZDS Lab 2 (đích) |
|---|---|---|
| Superset version | 2.1.1 | 5.0.0 |
| Metadata lưu ở | MySQL `zdslab1` (`.7`) | MySQL `zdslab2` (`.9`) |
| Database connection | 42 | 5 (đang dùng, **phải giữ**) |
| Schema | 35 | — |
| Dataset | 503 | — |
| User | 160 (149 active / 11 inactive) | có sẵn, số lượng riêng — **phải giữ** |
| User có chạy query | 106 / 160 | — |
| User active nhưng 6 tháng qua không chạy query | 115 | — |
| Data server đang trỏ tới | MySQL `.7` `.8` `.9`, Postgres | MySQL `.7` `.8`, Postgres, StarRocks `.6` `.11` `.12` |
| Đăng nhập | LDAP + OTP (Google Authenticator) | LDAP + OTP (Google Authenticator) |
| Alerts & Reports | Tắt (không có trong menu) | chưa kiểm tra |
| Row Level Security | Bật, nhưng **0 record** | chưa kiểm tra |
| Role tuỳ chỉnh (List Roles) | Có | chưa kiểm tra |
| Action Log | Có dữ liệu | chưa kiểm tra |

> ❗ Số liệu Lab 1 lấy từ kiểm kê thực tế trên production. Số liệu Lab 2 (user/connection hiện có, role, RLS, Alerts & Reports...) cần chạy `fake_data/preflight_inventory.py` trên Lab 2 thật để có số chính xác trước khi lên lịch — mục 6, Ngày 1.

## 3. Giải pháp

### Hai phương án

| | Phương án A — Dump & Restore | Phương án B — Export/Import theo object (chọn) |
|---|---|---|
| Cách làm | `mysqldump` toàn bộ metadata Lab 1 → restore đè lên database metadata Lab 2 | Dùng lệnh export của Superset (theo UUID) cho connection/dataset/dashboard; dùng script đọc–ghi trực tiếp cho user, role, lịch sử query |
| Giữ được metadata hiện có của Lab 2? | **Không** — bị ghi đè/xoá hoàn toàn | **Có** — chỉ thêm mới, không đụng object cũ |
| Tương thích khác version (2.1.1 → 5.0.0)? | Rủi ro cao: schema (cấu trúc bảng) giữa hai version khác nhau, chưa kiểm chứng có phục hồi được không | Có cơ chế chính thức của Superset để làm việc này, đã kiểm chứng ở lab |
| Downtime | Phải dừng Lab 2 để restore | Không cần dừng Lab 2 |
| Khả năng rollback | Khó — đã ghi đè thì mất bản gốc nếu không backup riêng | Dễ — backup metadata Lab 2 trước khi bắt đầu, rollback bằng cách restore lại đúng bản đó |
| Công sức | Thấp (1 lệnh) | Cao hơn — nhiều bước, cần script hỗ trợ |

**Chọn Phương án B**, vì yêu cầu bắt buộc là giữ nguyên metadata hiện có của Lab 2 — điều Phương án A không đáp ứng được ngay từ đầu, bất kể rủi ro khác.

### Cơ chế của Phương án B

| Loại metadata | Cách chuyển |
|---|---|
| Database connection, dataset | Export ra file `.zip` (UUID) → import vào Lab 2 kèm mật khẩu (giải mã từ Lab 1, mã hoá lại bởi Lab 2) |
| Dashboard, chart | Export ra file `.zip` (UUID) → import vào Lab 2 |
| Role tự tạo (nếu có) | Export role → **lọc bỏ** quyền tham chiếu ID cũ → import vào Lab 2 |
| User + role gán cho user | Script đọc bảng `ab_user` của Lab 1, ghi vào Lab 2 theo `username` (mật khẩu là hash một chiều, chép nguyên) |
| Lịch sử query, saved query | Script đọc bảng `query` / `saved_query` của Lab 1, ghi vào Lab 2, ánh xạ lại theo username + tên connection |

## 4. Cấu trúc hệ thống hiện tại

```
                    ┌─────────────────┐        ┌─────────────────┐
                    │   ZDS Lab 1      │        │   ZDS Lab 2      │
                    │  Superset 2.1.1  │        │  Superset 5.0.0  │
                    └────────┬─────────┘        └────────┬─────────┘
                             │ metadata                   │ metadata
                             ▼                            ▼
                    ┌─────────────────┐        ┌─────────────────┐
                    │ MySQL zdslab1    │        │ MySQL zdslab2    │
                    │   (.7)           │        │   (.9)           │
                    └─────────────────┘        └─────────────────┘

                     Cả hai Superset cùng đọc DỮ LIỆU THẬT (không migrate):

        ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
        │ MySQL          │  │ Postgres       │  │ StarRocks      │  │  (dữ liệu      │
        │ .7  .8  .9     │  │                │  │ .6  .11  .12   │  │   không đổi     │
        │ (Lab 1 dùng)   │  │ (cả 2 dùng)    │  │ (chỉ Lab 2)    │  │   trong migrate)│
        └───────────────┘  └───────────────┘  └───────────────┘  └───────────────┘
```

> ❗ Lab 1 và Lab 2 là **hai Superset độc lập**, mỗi Superset có metadata riêng. Chỉ có metadata (ai được truy cập gì, kết nối tới đâu, dashboard nào) di chuyển từ Lab 1 sang Lab 2. Bảng dữ liệu thật trong các MySQL/Postgres/StarRocks phía dưới **đứng yên** — cả hai Lab tiếp tục cùng đọc chúng, kể cả sau khi migrate xong.

## 5. Flow migrate

```
Bước 0 ─ Kiểm kê & xem trạng thái Lab 2 (không đổi gì)
   │
Bước 1 ─ Backup metadata Lab 2 (bắt buộc, để có đường lùi)
   │
Bước 2 ─ Export từ Lab 1: connection + dataset (.zip) , dashboard + chart (.zip)
   │
Bước 2b ─ Role tự tạo (nếu có): export → lọc → import vào Lab 2  ▶ phải xong TRƯỚC bước 3
   │
Bước 3 ─ Copy user + role-của-user: script đọc Lab 1 → ghi Lab 2 (theo username)
   │
Bước 4 ─ Lấy mật khẩu connection từ Lab 1 (giải mã) → import 2 file .zip vào Lab 2 (mã hoá lại)
   │        └─ xoá ngay file mật khẩu sau khi dùng
   │
Bước 5 ─ Vá lại cờ "đã xuất bản" của dashboard (2.1.1 không xuất trường này khi export)
   │
Bước 6 ─ Copy lịch sử SQL Lab + saved query: script đọc Lab 1 → ghi Lab 2 (theo username + tên connection)
   │
Bước 7 ─ superset db upgrade / superset init / restart Lab 2
   │
Bước 8 ─ Kiểm chứng: đối chiếu số liệu, test kết nối, test đăng nhập user cũ VÀ user có sẵn của Lab 2
```

**Vì sao đúng thứ tự này:** Bước 2b phải xong trước Bước 3 vì user cần role đã tồn tại mới gán được. Bước 3 phải xong trước Bước 4 và Bước 6 vì owner/người chạy query được gán theo username. Bước 4 phải xong trước Bước 6 vì lịch sử query gán theo tên connection, connection phải tồn tại trước.

**Trong suốt quá trình, Lab 2 không cần dừng dịch vụ** — người dùng hiện tại của Lab 2 vẫn dùng bình thường; metadata mới chỉ "xuất hiện thêm" sau Bước 4 trở đi.

## 6. Chi tiết cách làm — kế hoạch 1 tuần

Giả định: đã thống nhất cửa sổ bảo trì (nếu công ty yêu cầu), có quyền truy cập cả hai server MySQL metadata, và người thực hiện có tài khoản Admin (qua LDAP + OTP) trên cả hai Lab để tạo user kỹ thuật tạm dùng cho script.

| Ngày | Việc chính | Đầu ra |
|---|---|---|
| **Thứ 2** | **Kiểm kê & chuẩn bị.** Chạy `preflight_inventory.py` (chỉ đọc) trên cả hai Lab: đếm connection/user/dataset/dashboard hiện có, phát hiện trùng tên connection, trùng email/username, user tồn tại ở cả hai Lab nhưng khác role. Xác nhận `AUTH_TYPE`, `AUTH_ROLES_SYNC_AT_LOGIN` của Lab 2. Xác nhận Lab 1/Lab 2 dùng **cùng `SECRET_KEY`** hay khác (ảnh hưởng cách giải mã mật khẩu connection). Tạo user kỹ thuật tạm để script chạy được không cần OTP mỗi lần. | Báo cáo kiểm kê + danh sách xung đột cần xử lý trước khi migrate |
| **Thứ 3** | **Backup & rehearsal (môi trường lab/staging).** Backup metadata Lab 2 thật (mysqldump). Diễn tập toàn bộ luồng Bước 2 → 8 trên bản sao/staging giống production nhất có thể, để phát hiện lỗi trước khi đụng vào Lab 2 thật. | Bản backup Lab 2 + log diễn tập, danh sách lỗi phát sinh (nếu có) đã xử lý xong |
| **Thứ 4** | **Migrate role & user (Lab 2 thật).** Bước 2b (role tự tạo, nếu có) rồi Bước 3 (user). Đối chiếu ngay: số user thêm mới đúng bằng số user Lab 1 không trùng username với Lab 2; user trùng username bị bỏ qua đúng như dự kiến (không sửa gì ở Lab 2). | Lab 2 có đủ user + role của Lab 1, chưa có connection/dashboard mới |
| **Thứ 5** | **Migrate connection, dataset, dashboard (Bước 4, 5).** Xuất mật khẩu 42 connection từ Lab 1 (giải mã), import 2 file export vào Lab 2 (mã hoá lại bằng key Lab 2), xoá ngay file mật khẩu. Vá cờ published của dashboard. | Lab 2 có đủ 42+5 connection, 503 dataset, toàn bộ dashboard/chart của Lab 1 |
| **Thứ 6** | **Migrate lịch sử query & kiểm chứng toàn diện (Bước 6, 7, 8).** Copy lịch sử SQL Lab + saved query. `db upgrade` / `init` / restart Lab 2. Chạy kiểm chứng: đối chiếu số liệu hai bên, test từng connection kết nối được, test vài chart chạy ra dữ liệu, test đăng nhập bằng một số user cũ của Lab 1 **và** user có sẵn của Lab 2 (đảm bảo không bị ảnh hưởng). | Kết quả `MERGE OK` / `ALL CHECKS PASSED`; danh sách các mục **không** migrate được (Alerts & Reports, RLS, quyền role vào từng dataset, owner dashboard) đã ghi nhận để xử lý tay |
| **Cuối tuần (đệm)** | Theo dõi log, xử lý phát sinh nếu có. Nếu có vấn đề nghiêm trọng: rollback về bản backup Thứ 3. | Xác nhận ổn định trước khi thông báo người dùng chuyển hẳn sang Lab 2 |

> ❗ Kế hoạch trên giả định 42 connection không có bất thường lớn (không phát hiện xung đột nặng ở Thứ 2). Nếu kiểm kê Thứ 2 phát hiện nhiều trùng lặp (tên connection trùng nhưng khác UUID, user trùng email khác username...), thời gian xử lý Thứ 5–6 có thể kéo dài hơn — nên coi buổi cuối tuần là bộ đệm bắt buộc, không phải tuỳ chọn.

## 7. Đã chạy thử trên lab (máy host thật) & thời gian downtime

Toàn bộ luồng ở mục 5 đã được dựng và chạy thử trên máy host bằng Docker Compose — 5 container: `superset_lab1` (2.1.1), `superset_lab2` (5.0.0), `mysql_lab1`, `mysql_lab2`, `postgres_lab1` — với dữ liệu mô phỏng (5 connection, 10 dataset, 3 dashboard, 9 user ở Lab 1; 2 connection, 1 dashboard, 4 user có sẵn ở Lab 2). Kết quả: chạy hết Bước 0 → 8, kiểm chứng cuối cùng báo `MERGE OK`, cả 7 connection sau merge kết nối được, 13 chart chạy ra dữ liệu, user cũ của Lab 1 lẫn user có sẵn của Lab 2 đều đăng nhập được; chạy lại lần 2 không tạo dữ liệu trùng.

### Downtime đo được

| Giai đoạn | Lab 2 có dừng không? | Đo trên máy host |
|---|---|---|
| Bước 0–6 (kiểm kê, backup, export, role, user, import connection/dataset/dashboard, sync published, sync lịch sử query) | **Không** — mọi thao tác chạy thẳng vào database metadata hoặc gọi lệnh Superset ngay trong tiến trình, không đụng tới service đang chạy | 0 giây — đã xác nhận Lab 2 phục vụ bình thường suốt các bước này |
| Bước 7 (`superset db upgrade` → `superset init` → restart) | **Có** — đây là downtime thật duy nhất trong toàn quy trình | **Đo trực tiếp trên máy host của bạn**: gửi lệnh `docker compose restart superset_lab2` lúc t=0, liên tục gọi `curl http://localhost:8089/health` mỗi 0,2–0,3 giây → mất kết nối ngay từ t=0, service trả lời `200` trở lại ở **t ≈ 22,2 giây**. Lệnh `docker compose restart` tự nó báo "xong" ở t ≈ 3,9 giây, nhưng container còn phải chạy lại toàn bộ `bootstrap.sh` (`db upgrade` → `create-admin` → `init` → khởi động gunicorn) trước khi nhận request được, nên thời gian thực tế tính đến lúc dùng lại được là ~22 giây, không phải ~4 giây |

**Vậy trong kịch bản này, downtime của Lab 2 cho cả quy trình migrate xấp xỉ 20–25 giây**, xảy ra đúng một lần ở cuối (Bước 7), không rải rác trong lúc import dữ liệu.

### Vì sao con số này CHƯA thể dùng thẳng cho production

- Lab dùng 1 worker gunicorn (`gthread`, cấu hình tối giản trong `bootstrap.sh`) và `superset init` chỉ đồng bộ quyền cho 7 connection/10 dataset. Production có 42+ connection, 503 dataset → `superset init` (đồng bộ `ab_permission`/`ab_view_menu`/`ab_permission_view` cho từng dataset/connection) **nhiều khả năng chạy lâu hơn đáng kể**, có thể là phần chiếm thời gian chính trong khoảng downtime này.
- Lab restart bằng `docker compose restart` (dừng hẳn rồi khởi động lại, không có worker dự phòng). Nếu production chạy nhiều worker/instance phía sau load balancer và hỗ trợ **rolling restart** (khởi động worker mới trước khi tắt worker cũ), downtime có thể giảm về gần 0 — nhưng đây là thay đổi cách làm so với lab, cần hạ tầng thật hỗ trợ.
- Cách restart thật ở production chưa xác nhận (`systemd`, `supervisor`, script thủ công — mục cần xác nhận #5 trong [EXECUTION_HANDOFF.md](EXECUTION_HANDOFF.md)); thời gian khởi động lại có thể khác `docker compose restart`.

**Khuyến nghị:** đo lại đúng con số này trong buổi diễn tập trên bản sao production (kế hoạch Thứ 3, mục 6) trước khi thông báo cửa sổ downtime chính thức cho người dùng — con số 20–25 giây ở đây chỉ là mốc tham khảo từ quy mô lab, không phải cam kết cho hệ thống thật.

## 8. Rủi ro

| # | Rủi ro | Ảnh hưởng | Cách giảm thiểu |
|---|---|---|---|
| 1 | Quyền của role vào từng dataset/database (không phải quyền chung chung) không tự động chuyển được | User dùng role tự tạo hoặc Gamma có thể thấy **0 dataset** sau migrate dù connection đã có | Cấp lại quyền này bằng tay (hoặc script bổ sung) sau Bước 4, kiểm tra bằng cách đăng nhập thử một user Gamma |
| 2 | Owner của dashboard/dataset đổi thành người chạy import, không giữ owner gốc | User Alpha không chỉnh sửa được dashboard của chính mình | Map lại owner theo username sau khi import (cần thêm script, hiện README có nêu nhưng chưa xây) |
| 3 | Alerts & Reports, RLS, CSS template, annotation layer, tab SQL Lab đang mở, log, favorite, short link **không di chuyển** | Người dùng mất các cấu hình này nếu có sử dụng | Kiểm kê trước bằng `preflight_inventory.py`; hiện tại Lab 1 xác nhận Alerts & Reports tắt và RLS không có record nên rủi ro này thấp với production hiện tại |
| 4 | Đăng nhập LDAP + OTP khiến việc tự động hoá (login qua API/UI) khó thực hiện | Không thể chạy các bước import qua kịch bản cần đăng nhập lặp lại | Toàn bộ import/copy chạy **trong container**, không qua HTTP nên không cần OTP; chỉ thao tác qua UI (xem lại kết quả) mới cần đăng nhập, và đó là thao tác một lần của người thực hiện |
| 5 | `SECRET_KEY` khác nhau giữa hai Lab | Không ảnh hưởng vì import giải mã ở Lab 1 và mã hoá lại ở Lab 2 — nhưng cần xác nhận trước, nếu về sau đổi cách làm (dump/restore trực tiếp) thì sẽ hỏng | Xác nhận `SECRET_KEY` mỗi Lab ở bước kiểm kê (Thứ 2); giữ nguyên cách làm export/import, không chuyển sang dump/restore |
| 6 | Trùng tên connection giữa hai Lab nhưng là hai connection khác nhau (khác UUID) | Import báo lỗi trùng tên, dừng giữa chừng | Phát hiện trước ở bước kiểm kê (Thứ 2); đổi tên một bên trước khi import |
| 7 | Version Superset khác nhau khiến hành vi SQL Lab khác (ví dụ áp schema Postgres) | Query cũ chạy lại trên Lab 2 có thể ra kết quả khác so với lúc chạy trên Lab 1 | Thông báo trước cho người dùng; lịch sử copy sang chỉ là nhật ký (SQL + thời điểm), không phải kết quả đã cache |
| 8 | 115/160 user active nhưng 6 tháng qua không chạy query nào | Không phải rủi ro kỹ thuật, nhưng đáng cân nhắc: có thể loại bớt trước khi migrate để giảm số lượng cần xử lý | Có thể trao đổi với bên nghiệp vụ trước Thứ 2 xem có nên lọc bớt user không hoạt động hay chuyển hết |

---
Tài liệu thao tác chi tiết từng lệnh: [README.md](../README.md) (thực hành lab) · [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) (lý thuyết đầy đủ + các bẫy đã gặp) · [PRODUCTION_RUNBOOK.md](PRODUCTION_RUNBOOK.md) (runbook cho migrate thật).
