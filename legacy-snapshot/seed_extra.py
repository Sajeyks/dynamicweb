# One-off: adds the kinds of rows a long-lived installation has (blog posts,
# contact messages, hosting plans, supporters) on top of the sample data.
# Run on the original Django 1.9 stack, see legacy-snapshot/README.md.
from django.contrib.sites.models import Site
from django.utils import timezone
from djangocms_blog.models import BlogCategory, BlogConfig, Post

from datacenterlight.models import ContactUs
from digitalglarus.models import MembershipType, Supporter
from hosting.models import HostingPlan
from membership.models import CustomUser
from utils.models import ContactMessage

# start clean, so the script can be re-run
for model in (Post, BlogCategory, ContactMessage, ContactUs, HostingPlan,
              Supporter):
    model.objects.all().delete()

config = BlogConfig.objects.first()
author = CustomUser.objects.get(email='dummy-admin@example.com')
category = BlogCategory.objects.language('en').create(
    name='Operations', app_config=config)
for number in range(1, 9):
    post = Post.objects.language('en').create(
        title='Operations note {}'.format(number),
        slug='operations-note-{}'.format(number),
        abstract='<p>Short summary of note {}.</p>'.format(number),
        app_config=config, author=author, publish=True,
        date_published=timezone.now())
    post.categories.add(category)
    post.sites.add(Site.objects.get(domain='blog.ungleich.ch'))
for number in range(1, 9):
    ContactMessage.objects.create(
        name='Visitor {}'.format(number),
        email='visitor-{}@example.com'.format(number),
        message='Question number {} about hosting.'.format(number))
for number in range(1, 6):
    ContactUs.objects.create(
        name='Prospect {}'.format(number),
        email='prospect-{}@example.com'.format(number),
        message='Please send me an offer, request {}.'.format(number))
for cores, memory, disk in [(1, 1, 10), (2, 4, 40), (4, 8, 100)]:
    HostingPlan.objects.create(
        cpu_cores=cores, memory=memory, disk_size=disk)
for name in ['Hack4Glarus', 'Alpine Cloud', 'Linux Verein']:
    Supporter.objects.create(name=name, description='Supports the project.')
MembershipType.objects.get_or_create(name='standard', defaults={'price': 20})
print('legacy extras ready')
