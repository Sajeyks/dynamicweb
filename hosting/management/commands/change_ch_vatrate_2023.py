from django.core.management.base import BaseCommand
import datetime
import csv
import logging
import stripe
from hosting.models import VATRates
from utils.hosting_utils import get_vat_rate_for_country
from django.conf import settings
from membership.models import CustomUser, StripeCustomer

stripe.api_key = settings.STRIPE_API_PRIVATE_KEY

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '''CH vat rate changes on 2024-01-01 from 7.7% to 8.1%. This commands makes the necessary changes'''

    def handle(self, *args, **options):
        MAKE_MODIFS=False
        try:
            country_to_change = 'CH'
            currency_to_change = 'CHF'
            new_rate = 0.081
            user_country_vat_rate = get_vat_rate_for_country(country_to_change)
            logger.debug("Existing VATRate for %s %s " % (country_to_change, user_country_vat_rate))
            vat_rate = VATRates.objects.get(
                territory_codes=country_to_change, start_date__isnull=False, stop_date=None
            )
            logger.debug("VAT rate for %s is %s" % (country_to_change, vat_rate.rate))
            logger.debug("vat_rate object = %s" % vat_rate)
            logger.debug("Create end date for the VATRate %s" % vat_rate.id)
            if MAKE_MODIFS:
                vat_rate.stop_date = datetime.date(2023, 12, 31)
                vat_rate.save()
                print("Creating a new VATRate for CH")
                obj, created = VATRates.objects.get_or_create(
                    start_date=datetime.date(2024, 1, 1),
                    stop_date=None,
                    territory_codes=country_to_change,
                    currency_code=currency_to_change,
                    rate=new_rate,
                    rate_type="standard",
                    description="Switzerland standard VAT (added manually on %s)" % datetime.datetime.now()
                )
                if created:
                    logger.debug("Created new VAT Rate for %s with the new rate %s" % (country_to_change, new_rate))
                    logger.debug(obj)
                else:
                    logger.debug("VAT Rate for %s already exists with the rate %s" % (country_to_change, new_rate))

            logger.debug("Getting all subscriptions of %s that need a VAT Rate change")
            subscriptions = stripe.Subscription.list(limit=100)  # Increase the limit to 100 per page (maximum)
            ch_subs = []

            while subscriptions:
                for subscription in subscriptions:
                    if len(subscription.default_tax_rates) > 0 and subscription.default_tax_rates[0].jurisdiction and subscription.default_tax_rates[0].jurisdiction.lower() == 'ch':
                        ch_subs.append(subscription)
                    elif len(subscription.default_tax_rates) > 0:
                        print("subscription %s belongs to %s" % (subscription.id, subscription.default_tax_rates[0].jurisdiction))
                    else:
                        print("subscription %s does not have a tax rate" % subscription.id)
                if subscriptions.has_more:
                    print("FETCHING MORE")
                    subscriptions = stripe.Subscription.list(limit=100, starting_after=subscriptions.data[-1])
                else:
                    break
            logger.debug("There are %s ch subscription that need VAT rate update" % len(ch_subs))

            # CSV column headers
            csv_headers = [
                "customer_name",
                "subscription_id",
                "subscription_name",
                "amount",
                "vat_rate"
            ]
            # CSV file name
            csv_filename = "ch_subscriptions_change_2024.csv"
            # Write subscription data to CSV file
            with open(csv_filename, mode='w', newline='') as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=csv_headers)
                writer.writeheader()

                for subscription in ch_subs:
                    subscription_id = subscription["id"]
                    stripe_customer_id = subscription.get("customer", "")
                    vat_rate = subscription.get("tax_percent", "")
                    c_user = CustomUser.objects.get(
                        id=StripeCustomer.objects.filter(stripe_id=stripe_customer_id)[0].id)
                    customer_name = c_user.name.encode('utf-8')
                    customer_email = c.user_email
                    items = subscription.get("items", {}).get("data", [])
                    for item in items:
                        subscription_name = item.get("plan", {}).get("id", "")
                        amount = item.get("plan", {}).get("amount", "")

                        # Convert amount to a proper format (e.g., cents to dollars)
                        amount_in_chf = amount / 100  # Adjust this conversion as needed

                        # Writing to CSV
                        writer.writerow({
                            "customer_name": customer_name,
                            "customer_email": customer_email,
                            "stripe_customer_id": stripe_customer_id,
                            "subscription_id": subscription_id,
                            "subscription_name": subscription_name,
                            "amount": amount_in_chf,
                            "vat_rate": vat_rate  # Fill in VAT rate if available
                        })


            if MAKE_MODIFS:
                print("Making modifications now")
                tax_rate_obj = stripe.TaxRate.create(
                    display_name="VAT",
                    description="VAT for %s" % country_to_change,
                    jurisdiction=country_to_change,
                    percentage=new_rate,
                    inclusive=False,
                )
                stripe_tax_rate = StripeTaxRate.objects.create(
                    display_name=tax_rate_obj.display_name,
                    description=tax_rate_obj.description,
                    jurisdiction=tax_rate_obj.jurisdiction,
                    percentage=tax_rate_obj.percentage,
                    inclusive=False,
                    tax_rate_id=tax_rate_obj.id
                )

                for ch_sub in ch_subs:
                    ch_sub.default_tax_rates = [stripe_tax_rate.tax_rate_id]
                    ch_sub.save()
                    logger.debug("Default tax rate updated for %s" % ch_sub.id)
            else:
                print("Not making any modifications because MAKE_MODIFS=False")

        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
