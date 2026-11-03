"""migrate, made safe for databases restored from the old (Django 1.9) installation.

It replaces Django's own "migrate", so "python manage.py migrate" is all that has to run:
- brings the old django-reversion 1.x tables to the schema of the squashed 3.x migration
- skips the migration-history consistency check when it fails, as it does on old databases
  that record some migrations as applied before the (newer) migrations they now depend on
- gives pages that have no tree node one (see give_orphan_pages_a_node) before cms 0020
- makes sure every site in UNGLEICH_SITE_CONFIGS exists, and every host in
  UNGLEICH_SITE_ALIASES ({"alias host": "site domain"}) shows that site
"""
import json
import os

from django.contrib.sites.models import Site
from django.core.management.commands import migrate
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from multisite.models import Alias

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
            if not options['app_label'] and not self.cms_tree_done():
                # cms 0020 makes cms_page.node NOT NULL; stop before it to fix the pages
                # that 0018/0019 could not give a node
                executor = MigrationExecutor(connection)
                # forward steps only: asking for 0019 would also roll back whatever
                # an old database already has applied on top of it
                plan = [step for step in executor.migration_plan([('cms', '0019_set_pagenode')])
                        if not step[1]]
                if plan:
                    executor.migrate(None, plan=plan)
                self.give_orphan_pages_a_node()
        super().handle(*args, **options)
        if not dry_run and not options["app_label"]:
            for domain in json.loads(os.environ.get('UNGLEICH_SITE_CONFIGS') or '{}'):
                Site.objects.get_or_create(domain=domain, defaults={'name': domain})
            for alias, domain in json.loads(os.environ.get('UNGLEICH_SITE_ALIASES') or '{}').items():
                # no redirect to the site's canonical domain: the alias host is to be served
                Alias.objects.update_or_create(domain=alias, defaults={
                    'site': Site.objects.get(domain=domain), 'redirect_to_canonical': False})

    @staticmethod
    def cms_tree_done():
        return MigrationRecorder(connection).migration_qs.filter(
            app='cms', name='0020_old_tree_cleanup').exists()

    def give_orphan_pages_a_node(self):
        """Old databases have public pages that no draft page points to; cms 0019 gives
        nodes only to drafts and their public copies. Give each such page a node of its own
        (nothing is deleted), so that cms 0020 can make the column required."""
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, site_id, path, depth, numchild FROM cms_page '
                           'WHERE node_id IS NULL ORDER BY path')
            for page_id, site_id, path, depth, numchild in cursor.fetchall():
                cursor.execute('INSERT INTO cms_treenode (site_id, path, depth, numchild) '
                               'VALUES (%s, %s, %s, %s) RETURNING id', [site_id, path, depth, numchild])
                cursor.execute('UPDATE cms_page SET node_id = %s WHERE id = %s',
                               [cursor.fetchone()[0], page_id])
                self.stdout.write('  cms page %s had no tree node; gave it one' % page_id)

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
