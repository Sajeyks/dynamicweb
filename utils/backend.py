
import logging

from django.contrib.auth.backends import ModelBackend
logger = logging.getLogger(__name__)


class MyLDAPBackend(ModelBackend):
    def authenticate(self, username=None, password=None, **kwargs):
        user = super().authenticate(username, password, **kwargs)
        if user:
            user.create_ldap_account(password)
        return user
