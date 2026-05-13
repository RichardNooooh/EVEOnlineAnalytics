#!/usr/bin/env sh
set -eu

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=raw_files_password="$RAW_FILES_POSTGRES_PASSWORD" <<'EOSQL'
SELECT format('CREATE ROLE raw_files LOGIN PASSWORD %L', :'raw_files_password')
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = 'raw_files'
)\gexec

SELECT 'CREATE DATABASE raw_files OWNER raw_files'
WHERE NOT EXISTS (
  SELECT 1 FROM pg_database WHERE datname = 'raw_files'
)\gexec

GRANT ALL PRIVILEGES ON DATABASE raw_files TO raw_files;
EOSQL
