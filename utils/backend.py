
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

            # # User exists in Database
            # user.create_ldap_account()
            # # User does not have a username
            # if not user.username:
            #     assign_username(user)
            #
            # ldap_manager = LdapManager()
            # try:
            #     user_exists_in_ldap, entries = ldap_manager.check_user_exists(
            #         uid=user.username,
            #         attributes=['uid', 'givenName', 'sn', 'mail', 'userPassword'],
            #         search_base=settings.ENTIRE_SEARCH_BASE,
            #         search_attr='uid'
            #     )
            # except Exception:
            #     logger.exception("Exception occur while searching for user in LDAP")
            # else:
            #     ph = PasswordHasher()
            #     if user_exists_in_ldap:
            #         # User Exists in LDAP
            #         password_hash_from_ldap = entries[0]["userPassword"].value
            #         try:
            #             ph.verify(password_hash_from_ldap, password)
            #         except Exception:
            #             # Incorrect LDAP Password
            #             return None
            #         else:
            #             # Correct LDAP Password
            #             return user
            #     else:
            #         # User does not exists in LDAP
            #         if user.check_password(password):
            #             # Password is correct as per database
            #             first_name, last_name = get_first_and_last_name(user.name)
            #             if not last_name:
            #                 last_name = first_name
            #
            #             ldap_manager.create_user(user.username, password=ph.hash(password),
            #                                      firstname=first_name, lastname=last_name,
            #                                      email=user.email)
            #             user.password = "IN_LDAP"
            #             user.save()
            #             return user
            #         else:
            #             # Incorrect Password
            #             print("Incorrect password")
            #             return None

    def get_user(self, user_id):
        try:
            return CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return None
