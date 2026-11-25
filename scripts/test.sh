#!/bin/sh
# Lance les tests du back-end dans Docker. Usage : ./scripts/test.sh
# Les tests utilisent le role proprietaire (il cree une base de test), puis chaque test
# bascule sur le role applicatif pour verifier la Row-Level Security.
set -eu
docker compose run --rm backend sh -c 'DB_USER="$DB_OWNER_USER" DB_PASSWORD="$DB_OWNER_PASSWORD" python -m pytest "$@"' -- "$@"
