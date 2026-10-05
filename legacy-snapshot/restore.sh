#!/bin/sh
# Replaces the database of the running compose stack with the Django 1.9
# snapshot, then restarts the app (its start-up runs "migrate").
# Use it to check that an upgraded version can migrate old data:
#   sh legacy-snapshot/restore.sh
set -e
cd "$(dirname "$0")/.."
docker compose stop web celery
docker compose exec -T db psql -U app -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'app' AND pid <> pg_backend_pid()" > /dev/null
docker compose exec -T db psql -U app -d postgres -c "DROP DATABASE IF EXISTS app"
docker compose exec -T db psql -U app -d postgres -c "CREATE DATABASE app OWNER app"
gunzip -c legacy-snapshot/django-1.9.sql.gz | docker compose exec -T db psql -U app -d app -q -v ON_ERROR_STOP=1 > /dev/null
docker compose up -d web celery
echo "Restored. The site answers after about 1.5 minutes; then run: docker compose exec web python smoke_test.py"
