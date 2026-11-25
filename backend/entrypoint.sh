#!/bin/sh
# 1. Joue les migrations avec le role PROPRIETAIRE.
# 2. Lance le serveur avec le role APPLICATIF (soumis a la Row-Level Security).
set -eu

echo "Attente de PostgreSQL..."
until python -c "import psycopg, os; psycopg.connect(host=os.environ['DB_HOST'], dbname=os.environ['DB_NAME'], user=os.environ['DB_OWNER_USER'], password=os.environ['DB_OWNER_PASSWORD']).close()" 2>/dev/null; do
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
