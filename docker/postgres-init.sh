#!/bin/sh
# Execute UNE SEULE FOIS par l'image PostgreSQL, a la creation du volume de donnees.
# Cree deux roles :
#   - proprietaire (migrations) : possede les tables, ne contourne pas la RLS
#   - applicatif (execution)    : ni superutilisateur, ni BYPASSRLS, ni proprietaire
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${DB_OWNER_USER} LOGIN PASSWORD '${DB_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS CREATEDB;
CREATE ROLE ${DB_APP_USER} LOGIN PASSWORD '${DB_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
-- Permet aux tests (joues par le proprietaire) de se mettre dans la peau du role applicatif.
GRANT ${DB_APP_USER} TO ${DB_OWNER_USER};
CREATE DATABASE ${DB_NAME} OWNER ${DB_OWNER_USER};
SQL
