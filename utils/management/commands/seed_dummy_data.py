"""
Creates sample data for test environments so that every site shows realistic
content of its own (only into a database without page content), or, with
--purge, removes exactly what this command created.

Everything it creates is recognisable and self-contained:
  - per site, a published home page (reverse_id "dummy-home") with four
    child pages (reverse_id "dummy-<slug>")
  - a dummy admin (fixed login, see DUMMY_ADMIN_PASSWORD) and several dummy
    customers, all with dummy-*@example.com emails
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
CUSTOMER_EMAIL_FORMAT = 'dummy-customer-{}@example.com'
CUSTOMER_COUNT = 12
DEFAULT_ADMIN_PASSWORD = 'dummy-admin'
# domain -> (name, tagline); other domains are named after their domain
SITE_TEXTS = {
    'ungleich.ch': ('ungleich', 'Swiss IT infrastructure, hosting and open source.'),
    'blog.ungleich.ch': ('ungleich blog', 'Notes from running data centers, networks and free software.'),
    'comic.ungleich.ch': ('ungleich comic', 'Life in the data center, one panel at a time.'),
    'digitalglarus.ch': ('Digital Glarus', 'The Swiss IT valley in Schwanden, Glarus.'),
    'datacenterlight.ch': ('Data Center Light', 'Virtual machines from a Swiss, ecological data center.'),
    'rails-hosting.ch': ('Rails Hosting', 'Managed hosting for Ruby on Rails applications.'),
    'django-hosting.ch': ('Django Hosting', 'Managed hosting for Django applications.'),
    'node-hosting.ch': ('Node.js Hosting', 'Managed hosting for Node.js applications.'),
    'devuanhosting.ch': ('Devuan Hosting', 'Hosting on Devuan, the systemd-free Linux.'),
    'devuanhosting.com': ('Devuan Hosting', 'Hosting on Devuan, the systemd-free Linux.'),
}
# (slug, title, text) for the pages below each site's home page
SUB_PAGES = [
    ('about', 'About', '{name} is operated by ungleich GmbH in Switzerland. '
     'We run our own hardware and publish what we build as free software.'),
    ('services', 'Services', 'Virtual machines, managed hosting and '
     'consulting, all running in our own data centers.'),
    ('pricing', 'Pricing', 'Simple monthly plans, billed per resource '
     'with no minimum term.'),
    ('contact', 'Contact', 'Write to support@ungleich.ch and we will '
     'answer within one working day.'),
]
FIRST_NAMES = ['Anna', 'Luca', 'Marta', 'Jonas', 'Sofia', 'Noah', 'Elena',
               'Felix', 'Nina', 'Paul', 'Clara', 'Ivan']
LANGUAGE = 'en-us'
TEMPLATE = 'one_column.html'
# each site gets the CMS template it uses in production
SITE_TEMPLATES = {
    'ungleich.ch': 'page.html',
    'blog.ungleich.ch': 'page.html',
    'comic.ungleich.ch': 'page.html',
    'datacenterlight.ch': 'datacenterlight/cms/base.html',
    'digitalglarus.ch': 'home_digitalglarus.html',
}


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
        count = Page.objects.filter(reverse_id__startswith='dummy-').count()
        # deleting a home page also deletes its children and public copy
        for page in Page.objects.filter(reverse_id=REVERSE_ID,
                                        publisher_is_draft=True):
            page.delete()
        for page in Page.objects.filter(reverse_id__startswith='dummy-'):
            page.delete()
        users = CustomUser.objects.filter(
            email__startswith='dummy-', email__endswith='@example.com')
        user_count = users.count()
        users.delete()
        self.stdout.write("Removed {} dummy pages and {} users".format(
            count, user_count))

    def seed(self):
        # the app itself leaves a few empty pages; only pages with content
        # mean the database holds real data
        real = Page.objects.filter(
            publisher_is_draft=True, placeholders__cmsplugin__isnull=False
        ).exclude(reverse_id__startswith='dummy-')
        if real.exists():
            self.stdout.write(
                "Found existing page content, not adding dummy data")
            return
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
            password = os.environ.get(
                'DUMMY_ADMIN_PASSWORD') or DEFAULT_ADMIN_PASSWORD
            admin = CustomUser(
                email=ADMIN_EMAIL, name='Dummy Admin', validated=1,
                is_admin=True, is_superuser=True)
            admin.set_password(password)
            admin.save()
            self.stdout.write(
                "Dummy admin: {} / {}".format(ADMIN_EMAIL, password))
        for number in range(1, CUSTOMER_COUNT + 1):
            email = CUSTOMER_EMAIL_FORMAT.format(number)
            if CustomUser.objects.filter(email=email).exists():
                continue
            customer = CustomUser(
                email=email, validated=1 if number % 4 else 0,
                name='{} Dummy'.format(FIRST_NAMES[number - 1]))
            customer.set_password('dummy-customer')
            customer.save()

    def add_text(self, page, body):
        placeholder = page.placeholders.first()
        if placeholder is not None:
            add_plugin(placeholder, 'TextPlugin', LANGUAGE, body=body)
            # publish again so the public copy contains the plugin
            page.publish(LANGUAGE)

    def seed_page(self, site):
        if Page.objects.filter(reverse_id=REVERSE_ID, site=site).exists():
            return
        template = SITE_TEMPLATES.get(site.domain, TEMPLATE)
        name, tagline = SITE_TEXTS.get(
            site.domain, (site.domain, 'Welcome to {}.'.format(site.domain)))
        home = create_page(
            name, template, LANGUAGE, slug='home', meta_description=tagline,
            published=True, in_navigation=True, site=site,
            reverse_id=REVERSE_ID)
        self.add_text(home, '<h1>{}</h1><p>{}</p>'.format(name, tagline))
        for slug, title, text in SUB_PAGES:
            child = create_page(
                title, template, LANGUAGE, slug=slug,
                meta_description=text.format(name=name), published=True,
                in_navigation=True, site=site, parent=home,
                reverse_id='dummy-' + slug)
            self.add_text(
                child, '<h1>{}</h1><p>{}</p>'.format(
                    title, text.format(name=name)))
