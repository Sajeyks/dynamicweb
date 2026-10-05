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
from django.db.migrations.loader import MigrationLoader

# Databases created by older package versions can have a migration applied
# before the (newer) migrations it now depends on. Django refuses to migrate
# then, so apply those dependencies first with the history check switched off.
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

recorder = MigrationRecorder(connection)
recorder.ensure_schema()
legacy = recorder.migration_qs.filter(app='cmsplugin_filer_image').exists()
check = MigrationLoader.check_consistent_history
if legacy:
    MigrationLoader.check_consistent_history = lambda *args, **kwargs: None
try:
    if legacy:
        call_command('migrate', 'cmsplugin_filer_image', interactive=False, skip_checks=True)
finally:
    MigrationLoader.check_consistent_history = check
call_command('migrate', interactive=False, skip_checks=True)

from django.contrib.sites.models import Site
for domain in json.loads(os.environ.get('UNGLEICH_SITE_CONFIGS') or '{}'):
    Site.objects.get_or_create(domain=domain, defaults={'name': domain})
PYEOF

if [ "${SEED_DUMMY_DATA:-False}" = "True" ]; then
    python manage.py seed_dummy_data || echo 'seed_dummy_data failed, continuing'
fi

exec python manage.py runserver 0.0.0.0:8000
