import datetime
import logging

import stripe
# Create your views here.
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from utils.models import BillingAddress, UserBillingAddress
from utils.tasks import send_plain_email_task

logger = logging.getLogger(__name__)


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
        logger.debug("Tax_id %s is %s" % tax_id_obj.id,
                     tax_id_obj.verification.status)
        if tax_id_obj.verification.status == "verified":
            b_addresses = BillingAddress.objects.filter(vat_number=tax_id_obj.value)
            for b_address in b_addresses:
                b_address.vat_number_validated_on = datetime.datetime.now()

            ub_addresses = UserBillingAddress.objects.filter(vat_number=tax_id_obj.value)
            for ub_address in ub_addresses:
                ub_address.vat_number_validated_on = datetime.datetime.now()
        else:
            logger.debug("Tax_id %s is %s" % tax_id_obj.id,
                         tax_id_obj.verification.status)
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