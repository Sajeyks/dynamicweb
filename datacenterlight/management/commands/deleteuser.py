import logging
import oca
import sys
import stripe

from django.core.management.base import BaseCommand
from membership.models import CustomUser, DeletedUser
from hosting.models import (
    HostingOrder, HostingBill, VMDetail, UserCardDetail, UserHostingKey
)
from opennebula_api.models import OpenNebulaManager
logger = logging.getLogger(__name__)


def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")


class Command(BaseCommand):
    help = '''Deletes all resources of the user from the project'''

    def add_arguments(self, parser):
        parser.add_argument('customer_email', nargs='+', type=str)

    def handle(self, *args, **options):
        try:
            for email in options['customer_email']:
                r = query_yes_no("Are you sure you want to delete {} ?".format(
                    email, None
                ))
                if r:
                    logger.debug("Deleting user {}".format(email))
                    # Get stripe customer instance and delete the customer
                    try:
                        cus_user = CustomUser.objects.get(email=email)
                    except CustomUser.DoesNotExist as dne:
                        logger.error("CustomUser with email {} does "
                                     "not exist".format(email))
                        sys.exit(1)
                    stripe_customer = cus_user.stripecustomer
                    c = stripe.Customer.retrieve(
                        stripe_customer.stripe_id
                    )
                    cus_delete_obj = c.delete()
                    if cus_delete_obj.deleted:
                        logger.debug(
                            "StripeCustomer {} associated with {} deleted"
                            "".format(stripe_customer.stripe_id, email)
                        )
                    else:
                        logger.error("Error while deleting the StripeCustomer")

                    hosting_orders = HostingOrder.objects.filter(
                        customer=stripe_customer.id
                    )

                    vm_ids = []
                    for order in hosting_orders:
                        vm_ids.append(order.vm_id)

                        # Delete Billing Address
                        if order.billing_address is not None:
                            logger.debug(
                                "Billing Address {} associated with {} deleted"
                                "".format(order.billing_address.id, email)
                            )
                            order.billing_address.delete()
                        else:
                            logger.error(
                                "Error while deleting the billing_address")

                        # Delete order
                        if order is not None:
                            logger.debug(
                                "Order {} associated with {} deleted"
                                "".format(order.id, email)
                            )
                            order.delete()
                        else:
                            logger.error(
                                "Error while deleting the Order")

                    hosting_bills = HostingBill.objects.filter(
                        customer=stripe_customer.id
                    )

                    # delete hosting bills
                    for bill in hosting_bills:
                        if bill.billing_address is not None:
                            logger.debug(
                                "HostingBills billing address {} associated with {} deleted"
                                "".format(bill.billing_address.id, email)
                            )
                            bill.billing_address.delete()
                        else:
                            logger.error(
                                "Error while deleting the HostingBill's Billing address")

                        if bill is not None:
                            logger.debug(
                                "HostingBill {} associated with {} deleted"
                                "".format(bill.id, email)
                            )
                            bill.delete()
                        else:
                            logger.error(
                                "Error while deleting the HostingBill")

                    # delete VMDetail
                    for vm_id in vm_ids:
                        vm_detail = VMDetail.objects.get(vm_id=vm_id)
                        if vm_detail is not None:
                            logger.debug(
                                "vm_detail {} associated with {} deleted"
                                "".format(vm_detail.id, email)
                            )
                            vm_detail.delete()
                        else:
                            logger.error(
                                "Error while deleting the vm_detail")

                    # delete UserCardDetail
                    ucds = UserCardDetail.objects.filter(
                        stripe_customer=stripe_customer
                    )
                    for ucd in ucds:
                        if ucd is not None:
                            logger.debug(
                                "User Card Detail {} associated with {} deleted"
                                "".format(ucd.id, email)
                            )
                            ucd.delete()
                        else:
                            logger.error(
                                "Error while deleting the User Card Detail")

                    # delete UserHostingKey
                    uhks = UserHostingKey.objects.filter(
                        user=cus_user
                    )
                    for uhk in uhks:
                        uhk.delete()

                    # delete stripe customer
                    stripe_customer.delete()

                    # add user to deleteduser
                    DeletedUser.objects.create(
                        email=cus_user.email, name=cus_user.name,
                        user_id = cus_user.id
                    )

                    # delete CustomUser
                    cus_user.delete()

                    # remove user from OpenNebula
                    manager = OpenNebulaManager()
                    user_pool = manager._get_user_pool()
                    on_user = user_pool.get_by_name(email)
                    if on_user.id > 0:
                        logger.debug(
                            "Deleting user {} => ID={} from opennebula".format(
                                email, on_user.id)
                        )
                        manager.oneadmin_client.call(
                            oca.User.METHODS['delete'], on_user.id
                        )
                    else:
                        logger.error(
                            "User not found with email {}. "
                            "Not doing anything".format(email)
                        )

                    logger.debug("Deleted {} SUCCESSFULLY.".format(email))
        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
