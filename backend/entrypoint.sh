#!/bin/sh
# 1. Joue les migrations avec le role PROPRIETAIRE.
# 2. Lance le serveur avec le role APPLICATIF (soumis a la Row-Level Security).
set -eu

echo "Attente de PostgreSQL..."
tries=0
until python -c "import psycopg, os; psycopg.connect(host=os.environ['DB_HOST'], dbname=os.environ['DB_NAME'], user=os.environ['DB_OWNER_USER'], password=os.environ['DB_OWNER_PASSWORD']).close()" 2>/dev/null; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo ""
    echo "ERREUR : impossible de se connecter a PostgreSQL apres 60 secondes."
    echo "Cause la plus frequente : le fichier .env a ete modifie apres la creation de la base,"
    echo "ou la creation des roles a echoue (voir les lignes db-1 plus haut)."
    echo "Solution : corrige .env, puis lance  docker compose down -v  et  docker compose up --build"
    echo "(down -v efface la base locale de developpement)."
    echo ""
    exit 1
  fi
  sleep 1
done

echo "Migrations (role proprietaire)..."
DB_USER="$DB_OWNER_USER" DB_PASSWORD="$DB_OWNER_PASSWORD" python manage.py migrate --noinput

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

echo "Demarrage de l'API (role applicatif)..."
if [ "${DJANGO_DEBUG:-0}" = "1" ]; then
  exec python manage.py runserver 0.0.0.0:8000
else
  python manage.py collectstatic --noinput
  exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
fi
