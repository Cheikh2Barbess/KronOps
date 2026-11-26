#!/bin/sh
# Execute UNE SEULE FOIS par l'image PostgreSQL, a la creation du volume de donnees.
# Cree deux roles :
#   - proprietaire (migrations) : possede les tables, ne contourne pas la RLS
#   - applicatif (execution)    : ni superutilisateur, ni BYPASSRLS, ni proprietaire
set -eu

fail() {
  echo ""
  echo "ERREUR DE CONFIGURATION (fichier .env) : $1"
  echo "Corrige le fichier .env, puis lance : docker compose down -v  et  docker compose up --build"
  echo ""
  exit 1
}

check_name() {
  echo "$2" | grep -Eq '^[a-z_][a-z0-9_]*$' || fail "$1 doit contenir seulement des minuscules, chiffres et _ (valeur actuelle : '$2')."
}

check_password() {
  [ -n "$2" ] || fail "$1 est vide."
  echo "$2" | grep -Eq '^[A-Za-z0-9]+$' || fail "$1 doit contenir seulement des lettres et des chiffres."
}

check_name DB_NAME "$DB_NAME"
check_name DB_OWNER_USER "$DB_OWNER_USER"
check_name DB_APP_USER "$DB_APP_USER"
check_password DB_OWNER_PASSWORD "$DB_OWNER_PASSWORD"
check_password DB_APP_PASSWORD "$DB_APP_PASSWORD"
[ "$DB_OWNER_USER" != "$DB_APP_USER" ] || fail "DB_OWNER_USER et DB_APP_USER doivent etre differents."
[ "$DB_OWNER_USER" != "$POSTGRES_USER" ] && [ "$DB_APP_USER" != "$POSTGRES_USER" ] || fail "DB_OWNER_USER et DB_APP_USER ne doivent pas valoir '$POSTGRES_USER'."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${DB_OWNER_USER} LOGIN PASSWORD '${DB_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS CREATEDB;
CREATE ROLE ${DB_APP_USER} LOGIN PASSWORD '${DB_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
-- Permet aux tests (joues par le proprietaire) de se mettre dans la peau du role applicatif.
GRANT ${DB_APP_USER} TO ${DB_OWNER_USER};
CREATE DATABASE ${DB_NAME} OWNER ${DB_OWNER_USER};
SQL
