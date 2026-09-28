-- postgres_lab1: real data DBs that Superset (both labs) queries.

-- Read-only account used by the Superset connections.
CREATE ROLE reader LOGIN PASSWORD 'reader_pwd';

-- ------------------------------------------------------------------ finance
CREATE DATABASE finance;
\c finance

CREATE TABLE invoices (
  invoice_id  BIGINT PRIMARY KEY,
  customer_id BIGINT NOT NULL,
  total       NUMERIC(14,2) NOT NULL,
  currency    VARCHAR(3) NOT NULL,
  issued_at   TIMESTAMP NOT NULL
);
INSERT INTO invoices
SELECT n, 1 + (n * 7) % 300, round((50 + random() * 5000)::numeric, 2),
       (ARRAY['VND','USD','EUR'])[1 + n % 3],
       TIMESTAMP '2026-01-01' + (n % 240) * INTERVAL '1 day'
FROM generate_series(1, 2000) AS n;

CREATE TABLE payments (
  payment_id BIGINT PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(invoice_id),
  paid       NUMERIC(14,2) NOT NULL,
  method     VARCHAR(20) NOT NULL,
  paid_at    TIMESTAMP NOT NULL
);
INSERT INTO payments
SELECT n, 1 + n % 2000, round((20 + random() * 3000)::numeric, 2),
       (ARRAY['BANK','CARD','CASH','EWALLET'])[1 + n % 4],
       TIMESTAMP '2026-01-05' + (n % 230) * INTERVAL '1 day'
FROM generate_series(1, 1500) AS n;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO reader;

-- ------------------------------------------------------------------ warehouse
CREATE DATABASE warehouse;
\c warehouse

CREATE SCHEMA dw;
CREATE TABLE dw.dim_product (
  product_id BIGINT PRIMARY KEY,
  name       VARCHAR(100) NOT NULL,
  category   VARCHAR(100) NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
INSERT INTO dw.dim_product
SELECT n, 'Product ' || n, (ARRAY['Electronics','Fashion','Home','Beauty','Sports'])[1 + n % 5],
       TIMESTAMP '2026-01-01' + (n % 100) * INTERVAL '1 day'
FROM generate_series(1, 50) AS n;

CREATE TABLE dw.fact_revenue (
  date_key   DATE NOT NULL,
  region     VARCHAR(50) NOT NULL,
  product_id BIGINT NOT NULL REFERENCES dw.dim_product(product_id),
  revenue    NUMERIC(18,2) NOT NULL
);
INSERT INTO dw.fact_revenue
SELECT DATE '2026-01-01' + (n % 240), (ARRAY['North','Central','South'])[1 + n % 3],
       1 + n % 50, round((100 + random() * 10000)::numeric, 2)
FROM generate_series(1, 5000) AS n;

GRANT USAGE ON SCHEMA dw TO reader;
GRANT SELECT ON ALL TABLES IN SCHEMA dw TO reader;

-- ------------------------------------------------------------------ marketing
CREATE DATABASE marketing;
\c marketing

CREATE TABLE campaigns (
  campaign_id BIGINT PRIMARY KEY,
  name        VARCHAR(100) NOT NULL,
  channel     VARCHAR(50) NOT NULL,
  budget      NUMERIC(12,2) NOT NULL,
  start_date  DATE NOT NULL
);
INSERT INTO campaigns
SELECT n, 'Campaign ' || n, (ARRAY['Facebook','Google','TikTok','Email','Zalo'])[1 + n % 5],
       round((1000 + random() * 50000)::numeric, 2), DATE '2026-01-01' + (n * 7 % 200)
FROM generate_series(1, 40) AS n;

CREATE TABLE ad_clicks (
  click_id    BIGINT PRIMARY KEY,
  campaign_id BIGINT NOT NULL REFERENCES campaigns(campaign_id),
  cost        NUMERIC(10,4) NOT NULL,
  clicked_at  TIMESTAMP NOT NULL
);
INSERT INTO ad_clicks
SELECT n, 1 + n % 40, round((0.05 + random() * 2)::numeric, 4),
       TIMESTAMP '2026-01-01' + (n % 240) * INTERVAL '1 day' + (n % 24) * INTERVAL '1 hour'
FROM generate_series(1, 10000) AS n;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO reader;
