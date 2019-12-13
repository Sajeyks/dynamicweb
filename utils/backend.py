
import logging

from membership.models import CustomUser
logger = logging.getLogger(__name__)


class MyLDAPBackend(object):
    def authenticate(self, email, password):
        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            # User does not exists in Database
            return None
        else:
            user.create_ldap_account()
            if user.check_password(password):
                return user
            else:
                return None

    def get_user(self, user_id):
        try:
            return CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return None
