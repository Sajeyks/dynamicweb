"""
Creates dummy data for test environments so that every site shows something
different, or (with --purge) removes exactly what this command created.

Everything it creates is recognisable and self-contained:
  - one published CMS page per site, with reverse_id "dummy-home"
  - a dummy admin and a dummy customer, with the emails below
so it can be removed at any time without touching other data.

Run automatically on start-up when SEED_DUMMY_DATA=True (see start-web.sh).
"""
import json
import os
import random
import string

from cms.api import add_plugin, create_page
from cms.models import Page
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand

from membership.models import CustomUser

REVERSE_ID = 'dummy-home'
ADMIN_EMAIL = 'dummy-admin@example.com'
CUSTOMER_EMAIL = 'dummy-customer@example.com'
LANGUAGE = 'en-us'
TEMPLATE = 'one_column.html'


class Command(BaseCommand):
    help = "Create (or, with --purge, remove) dummy data for test environments"

    def add_arguments(self, parser):
        parser.add_argument('--purge', action='store_true',
                            help="remove the dummy data instead of creating it")

    def handle(self, *args, **options):
        if options['purge']:
            self.purge()
        else:
            self.seed()

    def purge(self):
        pages = Page.objects.filter(reverse_id=REVERSE_ID)
        count = pages.count()
        for page in pages:
            page.delete()
        users = CustomUser.objects.filter(
            email__in=[ADMIN_EMAIL, CUSTOMER_EMAIL]).delete()
        self.stdout.write("Removed {} dummy pages and {} user rows".format(
            count, users[0] if isinstance(users, tuple) else users))

    def seed(self):
        self.seed_users()
        for domain in self.site_domains():
            site = Site.objects.filter(domain=domain).first()
            if site is None:
                continue
            self.seed_page(site)
        self.stdout.write("Dummy data ready")

    def site_domains(self):
        configs = json.loads(settings.UNGLEICH_SITE_CONFIGS or '{}')
        return sorted(d for d in configs if ':' not in d)

    def seed_users(self):
        # built directly on the model: the user manager also creates LDAP
        # accounts, which don't exist in the test environment
        if not CustomUser.objects.filter(email=ADMIN_EMAIL).exists():
            password = os.environ.get('DUMMY_ADMIN_PASSWORD') or ''.join(
                random.SystemRandom().choice(string.ascii_letters + string.digits)
                for _ in range(16))
            admin = CustomUser(
                email=ADMIN_EMAIL, name='Dummy Admin', validated=1,
                is_admin=True, is_superuser=True)
            admin.set_password(password)
            admin.save()
            self.stdout.write(
                "Dummy admin: {} / {}".format(ADMIN_EMAIL, password))
        if not CustomUser.objects.filter(email=CUSTOMER_EMAIL).exists():
            customer = CustomUser(
                email=CUSTOMER_EMAIL, name='Dummy Customer', validated=1)
            customer.set_password('dummy-customer')
            customer.save()

    def seed_page(self, site):
        if Page.objects.filter(reverse_id=REVERSE_ID, site=site).exists():
            return
        page = create_page(
            '{} (dummy)'.format(site.domain), TEMPLATE, LANGUAGE,
            slug='dummy-home', published=True, in_navigation=True,
            site=site, reverse_id=REVERSE_ID)
        placeholder = page.placeholders.first()
        if placeholder is not None:
            add_plugin(
                placeholder, 'TextPlugin', LANGUAGE,
                body='<h1>{0}</h1><p>Dummy page for {0}.</p>'.format(
                    site.domain))
            # publish again so the public copy contains the plugin
            page.publish(LANGUAGE)
