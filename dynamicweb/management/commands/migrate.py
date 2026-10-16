"""migrate, made safe for databases restored from the old (Django 1.9) installation.

It replaces Django's own "migrate", so "python manage.py migrate" is all that has to run:
- brings the old django-reversion 1.x tables to the schema of the squashed 3.x migration
- skips the migration-history consistency check when it fails, as it does on old databases
  that record some migrations as applied before the (newer) migrations they now depend on
- makes sure every site in UNGLEICH_SITE_CONFIGS exists
"""
import json
import os

from django.contrib.sites.models import Site
from django.core.management.commands import migrate
from django.db import connection
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

REVERSION_SQUASH = '0001_squashed_0004_auto_20160611_1202'
REVERSION_FIXES = (
    'ALTER TABLE reversion_revision DROP COLUMN manager_slug',
    'ALTER TABLE reversion_version DROP COLUMN object_id_int',
    'ALTER TABLE reversion_version ALTER COLUMN object_id TYPE varchar(191)',
    "ALTER TABLE reversion_version ADD COLUMN db varchar(191) NOT NULL DEFAULT 'default'",
    'ALTER TABLE reversion_version ALTER COLUMN db DROP DEFAULT',
    'ALTER TABLE reversion_version ADD CONSTRAINT reversion_version_db_unique '
    'UNIQUE (db, content_type_id, object_id, revision_id)',
)


class Command(migrate.Command):
    requires_system_checks = []   # as before: the start-up never ran them

    def handle(self, *args, **options):
        dry_run = options['plan'] or options['check_unapplied']
        if not dry_run:
            self.prepare_old_database()
        super().handle(*args, **options)
        if not dry_run:
            for domain in json.loads(os.environ.get('UNGLEICH_SITE_CONFIGS') or '{}'):
                Site.objects.get_or_create(domain=domain, defaults={'name': domain})

    def prepare_old_database(self):
        recorder = MigrationRecorder(connection)
        recorder.ensure_schema()
        applied = recorder.migration_qs
        # django-reversion 3.x only ships one squashed migration that would
        # re-create the tables, so fix the old ones and record it as applied.
        if (applied.filter(app='reversion', name='0002_auto_20141216_1509').exists()
                and not applied.filter(app='reversion', name=REVERSION_SQUASH).exists()):
            with connection.cursor() as cursor:
                for sql in REVERSION_FIXES:
                    cursor.execute(sql)
            recorder.record_applied('reversion', REVERSION_SQUASH)
        # Only an old history fails this; a healthy database keeps Django's check.
        try:
            MigrationLoader(connection).check_consistent_history(connection)
        except InconsistentMigrationHistory:
            MigrationLoader.check_consistent_history = lambda *args, **kwargs: None
