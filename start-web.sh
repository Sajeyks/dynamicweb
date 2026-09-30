#!/bin/sh
# Container start-up for the web service: migrate, make sure every configured
# site exists in the DB, then serve.
set -ue
cd /usr/src/app
export DJANGO_SETTINGS_MODULE=dynamicweb.settings

python - <<'PYEOF'
import json, os
import django
django.setup()
from django.core.management import call_command
# system checks import urls.py, which queries the DB, so skip them here
call_command('migrate', interactive=False, skip_checks=True)

from django.contrib.sites.models import Site
for domain in json.loads(os.environ.get('UNGLEICH_SITE_CONFIGS') or '{}'):
    Site.objects.get_or_create(domain=domain, defaults={'name': domain})
PYEOF

if [ "${SEED_DUMMY_DATA:-False}" = "True" ]; then
    python manage.py seed_dummy_data || echo 'seed_dummy_data failed, continuing'
fi

exec python manage.py runserver 0.0.0.0:8000
