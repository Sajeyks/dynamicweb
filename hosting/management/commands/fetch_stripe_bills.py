import logging

from django.core.management.base import BaseCommand

from hosting.models import MonthlyHostingBill
from membership.models import CustomUser
from utils.stripe_utils import StripeUtils

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Fetches invoices from Stripe and creates bills for a given 
    customer in the MonthlyHostingBill model'''

    def add_arguments(self, parser):
        parser.add_argument('customer_email', nargs='+', type=str)

    def handle(self, *args, **options):
        try:
            for email in options['customer_email']:
                stripe_utils = StripeUtils()
                user = CustomUser.objects.get(email=email)
                if hasattr(user, 'stripecustomer'):
                    self.stdout.write(self.style.SUCCESS(
                        'Found %s. Fetching bills for him.' % email))
                    mhb = MonthlyHostingBill.objects.filter(
                        customer=user.stripecustomer).last()
                    created_gt = {}
                    if mhb is not None:
                        # fetch only invoices which is created after
                        # mhb.created, because we already have invoices till
                        # this date
                        created_gt = {'gt': mhb.created}

                    all_invoices_response = stripe_utils.get_all_invoices(
                        user.stripecustomer.stripe_id,
                        created=created_gt
                    )
                    if all_invoices_response['error'] is not None:
                        self.stdout.write(self.style.ERROR(all_invoices_response['error']))
                        exit(1)
                    all_invoices = all_invoices_response['response_object']
                    self.stdout.write(self.style.SUCCESS("Obtained {} invoices".format(len(all_invoices) if all_invoices is not None else 0)))
                    for invoice in all_invoices:
                        MonthlyHostingBill.create(
                            invoice, stripe_customer=user.stripecustomer
                        )
                else:
                    self.stdout.write(self.style.SUCCESS(
                        'Customer email %s does not have a stripe customer.' % email))
        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
