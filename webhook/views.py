import datetime
import logging

import stripe
# Create your views here.
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from membership.models import StripeCustomer

from utils.models import BillingAddress, UserBillingAddress
from utils.tasks import send_plain_email_task

logger = logging.getLogger(__name__)


# Things to do for webhooks feature
# 1. Uninstall old version and install a more recent version of stripe
#    ```
#    source venv/bin/activate
#    ./manage.py shell
#    pip uninstall stripe
#    pip install stripe==2.24.1
#    ```
# 2. Create tax id updated webhook
#    ```
#    ./manage.py webhook --create \
#    --webhook_endpoint https://datacenterlight.ch/en-us/webhooks/ \
#    --events_csv customer.tax_id.updated
#    ```
#
# 3. From the secret obtained in 2, setup an environment variable
#    ```
#    WEBHOOK_SECRET='whsec......'
#    ```


@require_POST
@csrf_exempt
def handle_webhook(request):
    payload = request.body
    event = None

    try:
        if 'HTTP_STRIPE_SIGNATURE' in request.META:
            sig_header = request.META['HTTP_STRIPE_SIGNATURE']
        else:
            logger.error("No HTTP_STRIPE_SIGNATURE header")
            # Invalid payload
            return HttpResponse(status=400)
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        err_msg = "FAILURE handle_invoice_webhook: Invalid payload details"
        err_body = "Details %s" % str(e)
        return handle_error(err_msg, err_body)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        err_msg = "FAILURE handle_invoice_webhook: SignatureVerificationError"
        err_body = "Details %s" % str(e)
        return handle_error(err_msg, err_body)

    # Do something with event
    logger.debug("Passed signature verification")

    if event.type == "customer.tax_id.updated":
        logger.debug("Webhook Event: customer.tax_id.updated")
        tax_id_obj = event.data.object
        logger.debug("Tax_id %s is %s" % (tax_id_obj.id,
                     tax_id_obj.verification.status))
        stripe_customer = None
        try:
            stripe_customer = StripeCustomer.objects.get(stripe_id=tax_id_obj.customer)
        except StripeCustomer.DoesNotExist as dne:
            logger.debug(
                "StripeCustomer %s does not exist" % tax_id_obj.customer)
        if tax_id_obj.verification.status == "verified":
            b_addresses = BillingAddress.objects.filter(stripe_tax_id=tax_id_obj.id)
            for b_address in b_addresses:
                b_address.vat_validation_status = tax_id_obj.verification.status
                b_address.vat_number_validated_on = datetime.datetime.now()
                b_address.save()

            ub_addresses = UserBillingAddress.objects.filter(stripe_tax_id=tax_id_obj.id)
            for ub_address in ub_addresses:
                ub_address.vat_validation_status = tax_id_obj.verification.status
                ub_address.vat_number_validated_on = datetime.datetime.now()
                ub_address.save()
            email_data = {
                'subject': "The VAT %s associated with %s was verified" %
                           (tax_id_obj.value,  stripe_customer.user.email if stripe_customer else "unknown"),
                'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
                'to': settings.DCL_ERROR_EMAILS_TO_LIST,
                'body': "The following objects were modified:\n".join(b_addresses).join(ub_addresses),
            }
        else:
            logger.debug("Tax_id %s is %s" % (tax_id_obj.id,
                         tax_id_obj.verification.status))
            email_data = {
                'subject': "The VAT %s associated with %s was %s" %
                           (tax_id_obj.value,  stripe_customer.user.email if stripe_customer else "unknown", tax_id_obj.verification.status),
                'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
                'to': settings.DCL_ERROR_EMAILS_TO_LIST,
                'body': "Response = %s" % str(tax_id_obj),
            }

        send_plain_email_task.delay(email_data)
    else:
        logger.error("Unhandled event : " + event.type)
    return HttpResponse(status=200)


def handle_error(error_msg, error_body):
    logger.error("%s -- %s" % (error_msg, error_body))
    email_to_admin_data = {
        'subject': error_msg,
        'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
        'to': [settings.ADMIN_EMAIL],
        'body': error_body,
    }
    send_plain_email_task.delay(email_to_admin_data)
    return HttpResponse(status=400)