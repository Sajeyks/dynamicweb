from django.core.management.base import BaseCommand
from datacenterlight.tasks import handle_metadata_and_emails
from datacenterlight.models import StripePlan
from opennebula_api.models import OpenNebulaManager
from membership.models import CustomUser
from hosting.models import GenericProduct
import logging
import json
import sys
import stripe

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Stripe plans created before version 3.4 saved the plan name like generic-{subscription_id}-amount. This
              command aims at replacing this with the actual product name
              '''

    def handle(self, *args, **options):
        cnt = 0
        self.stdout.write(
            self.style.SUCCESS(
                'In Fix generic stripe plan product names'
            )
        )
        plans_to_change = StripePlan.objects.filter(stripe_plan_id__startswith='generic')
        for plan in plans_to_change:
            response = input("Press 'y' to continue: ")

            # Check if the user entered 'y'
            if response.lower() == 'y':
                plan_name = plan.stripe_plan_id
                first_index_hyphen = plan_name.index("-") + 1
                product_id = plan_name[
                             first_index_hyphen:(plan_name[first_index_hyphen:].index("-")) + first_index_hyphen]
                gp = GenericProduct.objects.get(id=product_id)
                if gp:
                    cnt += 1
                # update stripe
                sp = stripe.Plan.retrieve(plan_name)
                pr = stripe.Product.retrieve(sp.product)
                pr.name = gp.product_name
                pr.save()
                # update local
                spl = StripePlan.objects.get(stripe_plan_id=plan_name)
                spl.stripe_plan_name = gp.product_name
                spl.save()
                print("%s. %s => %s" % (cnt, plan_name, gp.product_name))
            else:
                print("Invalid input. Please try again.")
                sys.exit()

        print("Done")