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

from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

recorder = MigrationRecorder(connection)
recorder.ensure_schema()
legacy = recorder.migration_qs.filter(app='cmsplugin_filer_image').exists()
# django-reversion 1.x tables: 3.x only ships one squashed migration that would
# re-create them, so bring the old tables to its schema and record it as applied.
squash = '0001_squashed_0004_auto_20160611_1202'
if (recorder.migration_qs.filter(app='reversion', name='0002_auto_20141216_1509').exists()
        and not recorder.migration_qs.filter(app='reversion', name=squash).exists()):
    with connection.cursor() as cursor:
        for sql in (
            'ALTER TABLE reversion_revision DROP COLUMN manager_slug',
            'ALTER TABLE reversion_version DROP COLUMN object_id_int',
            'ALTER TABLE reversion_version ALTER COLUMN object_id TYPE varchar(191)',
            "ALTER TABLE reversion_version ADD COLUMN db varchar(191) NOT NULL DEFAULT 'default'",
            'ALTER TABLE reversion_version ALTER COLUMN db DROP DEFAULT',
            'ALTER TABLE reversion_version ADD CONSTRAINT reversion_version_db_unique '
            'UNIQUE (db, content_type_id, object_id, revision_id)',
        ):
            cursor.execute(sql)
    recorder.record_applied('reversion', squash)
# Old databases can have a migration applied before the (newer) migrations it now
# depends on, which Django refuses; for them migrate with that check switched off.
if legacy:
    MigrationLoader.check_consistent_history = lambda *args, **kwargs: None
call_command('migrate', interactive=False, skip_checks=True)

from django.contrib.sites.models import Site
for domain in json.loads(os.environ.get('UNGLEICH_SITE_CONFIGS') or '{}'):
    Site.objects.get_or_create(domain=domain, defaults={'name': domain})
PYEOF

if [ "${SEED_DUMMY_DATA:-False}" = "True" ]; then
    python manage.py seed_dummy_data || echo 'seed_dummy_data failed, continuing'
fi

exec python manage.py runserver 0.0.0.0:8000
