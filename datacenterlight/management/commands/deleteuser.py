import logging
import oca
import sys
import stripe

from django.core.management.base import BaseCommand
from membership.models import CustomUser
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
                        order.billing_address.delete()
                        # Delete Order Detail
                        order.order_detail.delete()
                        # Delete order
                        order.delete()

                    hosting_bills = HostingBill.objects.filter(
                        customer=stripe_customer.id
                    )

                    # delete hosting bills
                    for bill in hosting_bills:
                        bill.billing_address.delete()
                        bill.delete()

                    # delete VMDetail
                    for vm_id in vm_ids:
                        vm_detail = VMDetail.objects.get(vm_id=vm_id)
                        vm_detail.delete()

                    # delete UserCardDetail
                    ucds = UserCardDetail.objects.filter(
                        stripe_customer=stripe_customer
                    )
                    for ucd in ucds:
                        ucd.delete()

                    # delete UserHostingKey
                    uhks = UserHostingKey.objects.filter(
                        user=cus_user
                    )
                    for uhk in uhks:
                        uhk.delete()

                    # delete stripe customer
                    stripe_customer.delete()

                    # delete CustomUser
                    cus_user.delete()

                    # remove user from OpenNebula
                    manager = OpenNebulaManager()
                    manager.oneadmin_client.call(
                        oca.User.METHODS['delete'], email
                    )

                    logger.debug("Deleted {} SUCCESSFULLY.".format(email))
        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
