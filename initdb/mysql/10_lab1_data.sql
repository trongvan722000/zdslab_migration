-- mysql_lab1 only: real data DBs that Superset (both labs) queries.
-- MySQL 8 caps recursive CTEs at 1000 rows by default; MariaDB (the real Lab 1 engine) has no such
-- variable (its own limit, max_recursive_iterations, is already huge), so only set it on MySQL.
SET @raise_cte_limit = IF(VERSION() LIKE '%MariaDB%', 'DO 0', 'SET SESSION cte_max_recursion_depth = 10000');
PREPARE raise_cte_limit FROM @raise_cte_limit;
EXECUTE raise_cte_limit;
DEALLOCATE PREPARE raise_cte_limit;

-- Read-only account used by the Superset connections.
CREATE USER IF NOT EXISTS 'reader'@'%' IDENTIFIED BY 'reader_pwd';
GRANT SELECT, SHOW VIEW ON sales.* TO 'reader'@'%';
GRANT SELECT, SHOW VIEW ON crm.* TO 'reader'@'%';
FLUSH PRIVILEGES;

-- ------------------------------------------------------------------ sales
CREATE DATABASE IF NOT EXISTS sales CHARACTER SET utf8mb4;
USE sales;

CREATE TABLE orders (
  order_id    BIGINT PRIMARY KEY,
  customer_id BIGINT NOT NULL,
  amount      DECIMAL(12,2) NOT NULL,
  status      VARCHAR(20) NOT NULL,
  order_date  DATETIME NOT NULL
);

INSERT INTO orders (order_id, customer_id, amount, status, order_date)
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 3000)
SELECT n,
       1 + (n * 7) % 300,
       ROUND(10 + RAND(n) * 490, 2),
       ELT(1 + n % 4, 'NEW', 'PAID', 'SHIPPED', 'CANCELLED'),
       TIMESTAMP('2026-01-01') + INTERVAL (n % 240) DAY + INTERVAL (n % 24) HOUR
FROM seq;

CREATE TABLE order_items (
  item_id  BIGINT PRIMARY KEY,
  order_id BIGINT NOT NULL,
  sku      VARCHAR(64) NOT NULL,
  qty      INT NOT NULL,
  price    DECIMAL(12,2) NOT NULL
);

INSERT INTO order_items (item_id, order_id, sku, qty, price)
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 8000)
SELECT n,
       1 + n % 3000,
       CONCAT('SKU-', LPAD(1 + (n * 13) % 50, 3, '0')),
       1 + n % 5,
       ROUND(5 + RAND(n) * 95, 2)
FROM seq;

-- ------------------------------------------------------------------ crm
CREATE DATABASE IF NOT EXISTS crm CHARACTER SET utf8mb4;
USE crm;

CREATE TABLE customers (
  customer_id BIGINT PRIMARY KEY,
  full_name   VARCHAR(255) NOT NULL,
  city        VARCHAR(100) NOT NULL,
  segment     VARCHAR(20) NOT NULL,
  created_at  DATETIME NOT NULL
);

INSERT INTO customers (customer_id, full_name, city, segment, created_at)
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 300)
SELECT n,
       CONCAT('Customer ', n),
       ELT(1 + n % 5, 'Ha Noi', 'Ho Chi Minh', 'Da Nang', 'Can Tho', 'Hai Phong'),
       ELT(1 + n % 3, 'SMB', 'Enterprise', 'Consumer'),
       TIMESTAMP('2025-06-01') + INTERVAL (n % 365) DAY
FROM seq;

CREATE TABLE tickets (
  ticket_id   BIGINT PRIMARY KEY,
  customer_id BIGINT NOT NULL,
  status      VARCHAR(20) NOT NULL,
  priority    VARCHAR(10) NOT NULL,
  opened_at   DATETIME NOT NULL
);

INSERT INTO tickets (ticket_id, customer_id, status, priority, opened_at)
WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 1200)
SELECT n,
       1 + (n * 11) % 300,
       ELT(1 + n % 3, 'OPEN', 'PENDING', 'CLOSED'),
       ELT(1 + n % 3, 'LOW', 'MEDIUM', 'HIGH'),
       TIMESTAMP('2026-01-01') + INTERVAL (n % 240) DAY
FROM seq;
