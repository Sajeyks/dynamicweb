import json
import logging
import sys

from django.core.management.base import BaseCommand
from membership.models import CustomUser
from hosting.models import (
    HostingOrder, VMDetail, UserCardDetail, UserHostingKey
)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Dumps the email addresses of all customers who have a VM'''

    def add_arguments(self, parser):
        parser.add_argument('-a', '--all_registered', action='store_true',
                            help='All registered users')

    def handle(self, *args, **options):
        all_registered = options['all_registered']
        all_customers_set = set()
        if all_registered:
            all_customers = CustomUser.objects.filter(
                is_admin=False, validated=True
            )
            for customer in all_customers:
                all_customers_set.add(customer.email)
                print(customer.email)
        else:
            all_hosting_orders = HostingOrder.objects.all()
            for order in all_hosting_orders:
                all_customers_set.add(order.customer.user.email)
                print(order.customer.user.email)

        print("Total customers = %s" % len(all_customers_set))
