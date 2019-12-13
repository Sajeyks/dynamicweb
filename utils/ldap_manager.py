import base64
import hashlib
import random
import ldap3
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class LdapManager:
    __instance = None

    def __new__(cls):
        if LdapManager.__instance is None:
            LdapManager.__instance = object.__new__(cls)
        return LdapManager.__instance

    def __init__(self):
        """
        Initialize the LDAP subsystem.
        """
        self.rng = random.SystemRandom()
        self.server = ldap3.Server(settings.AUTH_LDAP_SERVER)

    def get_admin_conn(self):
        """
        Return a bound :class:`ldap3.Connection` instance which has write
        permissions on the dn in which the user accounts reside.
        """
        conn = self.get_conn(user=settings.LDAP_ADMIN_DN,
                             password=settings.LDAP_ADMIN_PASSWORD,
                             raise_exceptions=True)
        conn.bind()
        return conn

    def get_conn(self, **kwargs):
        """
        Return an unbound :class:`ldap3.Connection` which talks to the configured
        LDAP server.

        The *kwargs* are passed to the constructor of :class:`ldap3.Connection` and
        can be used to set *user*, *password* and other useful arguments.
        """
        return ldap3.Connection(self.server, **kwargs)

    def _ssha_password(self, password):
        """
        Apply the SSHA password hashing scheme to the given *password*.
        *password* must be a :class:`bytes` object, containing the utf-8
        encoded password.

        Return a :class:`bytes` object containing ``ascii``-compatible data
        which can be used as LDAP value, e.g. after armoring it once more using
        base64 or decoding it to unicode from ``ascii``.
        """
        SALT_BYTES = 15

        sha1 = hashlib.sha1()
        salt = self.rng.getrandbits(SALT_BYTES * 8).to_bytes(SALT_BYTES,
                                                               "little")
        sha1.update(password)
        sha1.update(salt)

        digest = sha1.digest()
        passwd = b"{SSHA}" + base64.b64encode(digest + salt)
        return passwd

    def create_user(self, user, password, firstname, lastname, email):
        conn = self.get_admin_conn()
        uidNumber = self._get_max_uid() + 1
        logger.debug("uidNumber={uidNumber}".format(uidNumber=uidNumber))
        user_exists = True
        while user_exists:
            user_exists, _ = self.check_user_exists(
                "",
                '(&(objectClass=inetOrgPerson)(objectClass=posixAccount)'
                '(objectClass=top)(uidNumber={uidNumber}))'.format(
                    uidNumber=uidNumber
                )
            )
            if user_exists:
                logger.debug(
                    "{uid} exists. Trying next.".format(uid=uidNumber)
                )
                uidNumber += 1
        logger.debug("{uid} does not exist. Using it".format(uid=uidNumber))
        self._set_max_uid(uidNumber)
        try:
            uid = user.encode("utf-8")
            conn.add("uid={uid},{customer_dn}".format(
                    uid=uid, customer_dn=settings.LDAP_CUSTOMER_DN
                ),
                ["inetOrgPerson", "posixAccount", "ldapPublickey"],
                {
                    "uid": [uid],
                    "sn": [lastname.encode("utf-8")],
                    "givenName": [firstname.encode("utf-8")],
                    "cn": [uid],
                    "displayName": ["{} {}".format(firstname, lastname).encode("utf-8")],
                    "uidNumber": [str(uidNumber)],
                    "gidNumber": [str(settings.LDAP_CUSTOMER_GROUP_ID)],
                    "loginShell": ["/bin/bash"],
                    "homeDirectory": ["/home/{}".format(user).encode("utf-8")],
                    "mail": email.encode("utf-8"),
                    "userPassword": [password.encode("utf-8")]
                }
            )
            logger.debug('Created user %s %s' % (user.encode('utf-8'),
                                                 uidNumber))
        except Exception as ex:
            logger.debug('Could not create user %s' % user.encode('utf-8'))
            logger.error("Exception: " + str(ex))
            raise Exception(ex)
        finally:
            conn.unbind()

    def change_password(self, uid, new_password):
        """
        Changes the password of the user identified by user_dn

        :param uid: str The uid that identifies the user
        :param new_password: str The new password string
        :return: True if password was changed successfully False otherwise
        """
        conn = self.get_admin_conn()

        # Make sure the user exists first to change his/her details
        user_exists, entries = self.check_user_exists(
            uid=uid,
            search_base=settings.ENTIRE_SEARCH_BASE
        )
        return_val = False
        if user_exists:
            try:
                return_val = conn.modify(
                    entries[0].entry_dn,
                    {
                        "userpassword": (
                            ldap3.MODIFY_REPLACE,
                            [new_password.encode("utf-8")]
                        )
                    }
                )
            except Exception as ex:
                logger.error("Exception: " + str(ex))
        else:
            logger.error("User {} not found".format(uid))

        conn.unbind()
        return return_val


    def change_user_details(self, uid, details):
        """
        Updates the user details as per given values in kwargs of the user
        identified by user_dn.

        Assumes that all attributes passed in kwargs are valid.

        :param uid: str The uid that identifies the user
        :param details: dict A dictionary containing the new values
        :return: True if user details were updated successfully False otherwise
        """
        conn = self.get_admin_conn()

        # Make sure the user exists first to change his/her details
        user_exists, entries = self.check_user_exists(
            uid=uid,
            search_base=settings.ENTIRE_SEARCH_BASE
        )

        return_val = False
        if user_exists:
            details_dict = {k: (ldap3.MODIFY_REPLACE, [v.encode("utf-8")]) for
                            k, v in details.items()}
            try:
                return_val = conn.modify(entries[0].entry_dn, details_dict)
                msg = "success"
            except Exception as ex:
                msg = str(ex)
                logger.error("Exception: " + msg)
            finally:
                conn.unbind()
        else:
            msg = "User {} not found".format(uid)
            logger.error(msg)
            conn.unbind()
        return return_val, msg

    def check_user_exists(self, uid, search_filter="", attributes=None,
                          search_base=settings.LDAP_CUSTOMER_DN, search_attr="uid"):
        """
        Check if the user with the given uid exists in the customer group.

        :param uid: str representing the user
        :param search_filter: str representing the filter condition to find
                            users. If its empty, the search finds the user with
                            the given uid.
        :param attributes: list A list of str representing all the attributes
                           to be obtained in the result entries
        :param search_base: str
        :return: tuple (bool, [ldap3.abstract.entry.Entry ..])
                       A bool indicating if the user exists
                       A list of all entries obtained in the search
        """
        conn = self.get_admin_conn()
        entries = []
        try:
            result = conn.search(
                search_base=search_base,
                search_filter=search_filter if len(search_filter) > 0 else
                '(uid={uid})'.format(uid=uid),
                attributes=attributes
            )
            entries = conn.entries
        finally:
            conn.unbind()
        return result, entries

    def delete_user(self, uid):
        """
        Deletes the user with the given uid from ldap

        :param uid: str representing the user
        :return: True if the delete was successful False otherwise
        """
        conn = self.get_admin_conn()
        try:
            return_val = conn.delete(
                ("uid={uid}," + settings.LDAP_CUSTOMER_DN).format(uid=uid),
            )
            msg = "success"
        except Exception as ex:
            msg = str(ex)
            logger.error("Exception: " + msg)
            return_val = False
        finally:
            conn.unbind()
        return return_val, msg

    def _set_max_uid(self, max_uid):
        """
        a utility function to save max_uid value to a file

        :param max_uid: an integer representing the max uid
        :return:
        """
        with open(settings.LDAP_MAX_UID_FILE_PATH, 'w+') as handler:
            handler.write(str(max_uid))

    def _get_max_uid(self):
        """
        A utility function to read the max uid value that was previously set

        :return: An integer representing the max uid value that was previously
         set
        """
        try:
            with open(settings.LDAP_MAX_UID_FILE_PATH, 'r+') as handler:
                try:
                    return_value = int(handler.read())
                except ValueError as ve:
                    logger.error(
                        "Error reading int value from {}. {}"
                        "Returning default value {} instead".format(
                            settings.LDAP_MAX_UID_PATH,
                            str(ve),
                            settings.LDAP_DEFAULT_START_UID
                        )
                    )
                    return_value = settings.LDAP_DEFAULT_START_UID
                return return_value
        except FileNotFoundError as fnfe:
            logger.error("File not found : " + str(fnfe))
            return_value = settings.LDAP_DEFAULT_START_UID
            logger.error("So, returning UID={}".format(return_value))
            return return_value

