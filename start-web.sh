#!/bin/sh
# Container start-up for the web service: migrate, make sure every configured
# site exists in the DB, then serve with gunicorn.
# RUN_MIGRATIONS=False skips the migrations (when a separate job runs them);
# MIGRATE_ONLY=True exits after them.
set -ue
cd /usr/src/app
export DJANGO_SETTINGS_MODULE=dynamicweb.settings

if [ "${RUN_MIGRATIONS:-True}" = "True" ]; then
    python manage.py migrate --noinput
fi

if [ "${MIGRATE_ONLY:-False}" = "True" ]; then
    exit 0
fi

if [ "${SEED_DUMMY_DATA:-False}" = "True" ]; then
    python manage.py seed_dummy_data || echo 'seed_dummy_data failed, continuing'
fi

# Served by WhiteNoise
python manage.py collectstatic --noinput -v0

exec gunicorn dynamicweb.wsgi:application --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - --error-logfile -
