import logging

from django.core.management.base import BaseCommand

from hosting.models import (
    HostingOrder, VMDetail
)
from membership.models import CustomUser

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
        else:
            all_hosting_orders = HostingOrder.objects.filter()
            running_vm_details = VMDetail.objects.filter(terminated_at=None)
            running_vm_ids = [rvm.vm_id for rvm in running_vm_details]
            for order in all_hosting_orders:
                if order.vm_id in running_vm_ids:
                    all_customers_set.add(order.customer.user.email)
        for cu in all_customers_set:
            print(cu)
        if all_registered:
            print("All registered users = %s" % len(all_customers_set))
        else:
            print("Total active customers = %s" % len(all_customers_set))
