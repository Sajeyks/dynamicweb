import logging
import sys
from pprint import pprint

from django.core.management.base import BaseCommand
from membership.models import CustomUser
from hosting.models import (
    HostingOrder, VMDetail, UserCardDetail, UserHostingKey
)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Dumps the data of a customer into a json file'''

    def add_arguments(self, parser):
        parser.add_argument('customer_email', nargs='+', type=str)

    def handle(self, *args, **options):
        try:
            for email in options['customer_email']:
                logger.debug("Creating dump for the user {}".format(email))
                try:
                    cus_user = CustomUser.objects.get(email=email)
                except CustomUser.DoesNotExist as dne:
                    logger.error("CustomUser with email {} does "
                                 "not exist".format(email))
                    sys.exit(1)

                hosting_orders = HostingOrder.objects.filter(
                    customer=cus_user.stripecustomer.id
                )

                vm_ids = []
                orders_dict = {}
                for order in hosting_orders:
                    order_dict = {}
                    vm_ids.append(order.vm_id)
                    order_dict["VM_ID"] = order.vm_id
                    order_dict["Order Nr."] = order.id
                    order_dict["Created On"] = str(order.created_on)
                    order_dict["Price"] = order.price
                    order_dict["Payment card details"] = {
                        "last4": order.last4,
                        "brand": order.cc_brand
                    }
                    if order.subscription_id is not None and order.stripe_charge_id is None:
                        order_dict["Order type"] = "Monthly susbcription"
                    else:
                        order_dict["Order type"] = "One time payment"

                    # billing address
                    if order.billing_address is not None:
                        order_dict["Billing Address"] = {
                            "Street": order.billing_address.street_address,
                            "City": order.billing_address.city,
                            "Country": order.billing_address.country,
                            "Postal code": order.billing_address.postal_code,
                            "Card holder name": order.billing_address.cardholder_name
                        }
                    else:
                        logger.error(
                            "did not find billing_address")

                    # Order Detail
                    if order.order_detail is not None:
                        order_dict["Specifications"] = {
                            "RAM": "{} GB".format(order.order_detail.memory),
                            "Cores": order.order_detail.cores,
                            "Disk space (SSD)": "{} GB".format(
                                order.order_detail.ssd_size)
                        }
                    else:
                        logger.error(
                            "Did not find order_detail. None")

                    vm_detail = VMDetail.objects.get(vm_id=order.vm_id)
                    if vm_detail is not None:
                        order_dict["VM Details"] = {
                            "VM_ID": order.vm_id,
                            "IPv4": vm_detail.ipv4,
                            "IPv6": vm_detail.ipv6,
                            "OS": vm_detail.configuration,
                        }
                        order_dict["Terminated on"] = vm_detail.terminated_at

                    orders_dict[order.vm_id] = order_dict


                # UserCardDetail
                cards = {}
                ucds = UserCardDetail.objects.filter(
                    stripe_customer=cus_user.stripecustomer
                )
                for ucd in ucds:
                    card = {}
                    if ucd is not None:
                        card["Last 4"] = ucd.last4
                        card["Brand"] = ucd.brand
                        card["Expiry month"] = ucd.exp_month
                        card["Expiry year"] = ucd.exp_year
                        card["Preferred"] = ucd.preferred
                        cards[ucd.id] = card
                    else:
                        logger.error(
                            "Error while deleting the User Card Detail")

                # UserHostingKey
                keys = {}
                uhks = UserHostingKey.objects.filter(
                    user=cus_user
                )
                for uhk in uhks:
                    key = {
                        "Public key": uhk.public_key,
                        "Name": uhk.name,
                        "Created on": str(uhk.created_at)
                    }
                    if uhk.private_key is not None:
                        key["Private key"] = uhk.private_key
                    keys[uhk.name] = key
                print("User {} dump is follows:")
                output_dict = {
                    "User details": {
                        "Name": cus_user.name,
                        "Email": cus_user.email,
                        "Activated": "yes" if cus_user.validated == 1 else "no",
                        "Last login": str(cus_user.last_login)
                    },
                    "Orders": orders_dict,
                    "Payment cards": cards,
                    "SSH Keys": keys
                }
                pprint(output_dict)
                logger.debug("Dumped user {} SUCCESSFULLY.".format(email))
        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
