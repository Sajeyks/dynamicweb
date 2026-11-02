#!/bin/sh
# Container start-up for the web service: optionally seed dummy data, then serve with gunicorn.
# The migrations run beforehand (ROLE=migrate); static files are collected at build time.
set -ue
cd /usr/src/app
export DJANGO_SETTINGS_MODULE=dynamicweb.settings

if [ "${SEED_DUMMY_DATA:-False}" = "True" ]; then
    python manage.py seed_dummy_data || echo 'seed_dummy_data failed, continuing'
fi

exec gunicorn dynamicweb.wsgi:application --bind '[::]:8000' \
    --workers "${GUNICORN_WORKERS:-3}" --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - --error-logfile -
