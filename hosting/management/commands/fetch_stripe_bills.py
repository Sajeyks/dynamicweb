from django.core.management.base import BaseCommand

from hosting.models import UserCardDetail
from membership.models import CustomUser
from utils.stripe_utils import StripeUtils


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
                    self.stdout.write(self.style.SUCCESS('Found %s. Fetching bills for him.' % email))
                    stripe_utils.get_all_invoices(
                        user.stripecustomer.stripe_id
                    )
                else:
                    self.stdout.write(self.style.SUCCESS('Customer email %s does not have a stripe customer.' % email))
        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
