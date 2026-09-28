-- Runs on BOTH mysql_lab1 and mysql_lab2: the Superset metadata DB + its owner.
CREATE DATABASE IF NOT EXISTS superset_meta CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'superset'@'%' IDENTIFIED BY 'superset';
GRANT ALL PRIVILEGES ON superset_meta.* TO 'superset'@'%';
FLUSH PRIVILEGES;
