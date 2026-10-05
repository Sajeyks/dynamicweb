from .base import * # flake8: noqa

REGISTRATION_MESSAGE['message'] = REGISTRATION_MESSAGE['message'].format(host='dynamicweb-development.ungleich.ch',
                                                                         slug='{slug}')
ALLOWED_HOSTS = [
    "*"
    ]

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake'
    }
}

MIDDLEWARE_CLASSES = (
    'utils.middleware.DevSiteSwitcherMiddleware',
) + MIDDLEWARE_CLASSES

MIDDLEWARE_CLASSES += ("debug_toolbar.middleware.DebugToolbarMiddleware",)

INSTALLED_APPS += (
    'django_extensions',
    # debug_toolbar seems to conflict with multisite (and djangocms_multisite)
    #   'debug_toolbar'
    )

# Without an LDAP server (e.g. the docker test stack) log in with plain Django
# authentication, otherwise every successful login fails creating the LDAP account
if not AUTH_LDAP_SERVER:
    AUTHENTICATION_BACKENDS = tuple(
        'django.contrib.auth.backends.ModelBackend'
        if backend == 'utils.backend.MyLDAPBackend' else backend
        for backend in AUTHENTICATION_BACKENDS)
