"""
Aliases for helpers that newer Django versions removed.

The unmaintained aldryn-* packages (and similar) still import them. Imported
first thing from the settings, before any app code is loaded.
"""
import django.utils.encoding
import django.utils.translation

if not hasattr(django.utils.encoding, 'python_2_unicode_compatible'):
    django.utils.encoding.python_2_unicode_compatible = lambda cls: cls

for _name in ('gettext', 'gettext_lazy', 'gettext_noop',
              'ngettext', 'ngettext_lazy'):
    if not hasattr(django.utils.translation, 'u' + _name):
        setattr(django.utils.translation, 'u' + _name,
                getattr(django.utils.translation, _name))

import sys

import six
from django.conf import urls
from django.db import models
from django.http import HttpRequest
from django.urls import re_path
from django.utils import encoding

for _name, _target in (('force_text', 'force_str'), ('smart_text', 'smart_str'),
                       ('force_unicode', 'force_str')):
    if not hasattr(encoding, _name):
        setattr(encoding, _name, getattr(encoding, _target))

if not hasattr(urls, 'url'):
    urls.url = re_path

if 'django.utils.six' not in sys.modules:
    import django.utils
    django.utils.six = six
    sys.modules['django.utils.six'] = six
    sys.modules['django.utils.six.moves'] = six.moves

if not hasattr(models, 'NullBooleanField'):
    class NullBooleanField(models.BooleanField):
        def __init__(self, *args, **kwargs):
            kwargs['null'] = True
            kwargs['blank'] = True
            super().__init__(*args, **kwargs)

        def deconstruct(self):
            name, path, args, kwargs = super().deconstruct()
            del kwargs['null'], kwargs['blank']
            return name, path, args, kwargs

    models.NullBooleanField = NullBooleanField

if not hasattr(HttpRequest, 'is_ajax'):
    HttpRequest.is_ajax = lambda self: self.headers.get('x-requested-with') == 'XMLHttpRequest'


from django.apps import AppConfig


class CompatConfig(AppConfig):
    """Shims that need the app registry; listed first in INSTALLED_APPS so
    they are in place before the admin modules of other apps are imported."""
    name = 'dynamicweb'
    label = 'dynamicweb_compat'

    def ready(self):
        from django.contrib.admin import options
        from django.contrib.auth import admin as auth_admin

        if not hasattr(auth_admin, 'csrf_protect_m'):
            auth_admin.csrf_protect_m = options.csrf_protect_m

        # Django 6's change list templates read "cl.opts"; the django-cms 3.11
        # page tree view only passes "opts", which breaks the page list.
        from types import SimpleNamespace
        from cms.admin.pageadmin import BasePageAdmin

        changelist_view = BasePageAdmin.changelist_view

        def changelist_view_with_cl(self, request, extra_context=None):
            response = changelist_view(self, request, extra_context)
            if hasattr(response, 'context_data'):
                response.context_data.setdefault('cl', SimpleNamespace(opts=self.model._meta))
            return response

        BasePageAdmin.changelist_view = changelist_view_with_cl

        # django-treebeard 7 renamed the form fields "_position" and
        # "_ref_node_id" to "treebeard_position" and "treebeard_ref_node";
        # aldryn-categories still lists the old names in its admin.
        from aldryn_categories.admin import CategoryAdmin
        from parler.admin import TranslatableAdmin

        CategoryAdmin.fieldsets = (
            (None, {'fields': ('name', 'slug')}),
            (' ', {'fields': ('treebeard_position', 'treebeard_ref_node')}),
        )
        CategoryAdmin.get_form = lambda self, request, obj=None, **kwargs: (
            TranslatableAdmin.get_form(self, request, obj, **kwargs))
