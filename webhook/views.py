import datetime
import logging
import json
import stripe

# Create your views here.
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from datacenterlight.views import do_provisioning, do_provisioning_generic
from membership.models import StripeCustomer
from hosting.models import IncompleteSubscriptions, IncompletePaymentIntents

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
                'body': "The following objects were modified:\n".join(
                    '\n'.join([str(b_address) for b_address in b_addresses])
                ).join(
                    '\n'.join([str(ub_address) for ub_address in ub_addresses])
                ),
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
    elif event.type == 'invoice.paid':
        #More info:  https://stripe.com/docs/billing/migration/strong-customer-authentication#scenario-1-handling-fulfillment
        invoice_obj = event.data.object
        logger.debug("Webhook Event: invoice.paid")
        logger.debug("invoice_obj %s " % str(invoice_obj))
        logger.debug("invoice_obj.paid = %s %s" % (invoice_obj.paid, type(invoice_obj.paid)))
        logger.debug("invoice_obj.billing_reason = %s %s" % (invoice_obj.billing_reason, type(invoice_obj.billing_reason)))
        # We should check for billing_reason == "subscription_create" but we
        # check for "subscription_update"
        # because we are using older api.
        # See https://stripe.com/docs/upgrades?since=2015-07-13

        # The billing_reason attribute of the invoice object now can take the
        # value of subscription_create, indicating that it is the first
        # invoice of a subscription. For older API versions,
        # billing_reason=subscription_create is represented as
        # subscription_update.

        if (invoice_obj.paid and
                invoice_obj.billing_reason == "subscription_update"):
            logger.debug("""invoice_obj.paid and
                invoice_obj.billing_reason == subscription_update""")
            logger.debug("Start provisioning")
            try:
                stripe_subscription_obj = stripe.Subscription.retrieve(
                    invoice_obj.subscription)
                try:
                    incomplete_sub = IncompleteSubscriptions.objects.get(
                        subscription_id=invoice_obj.subscription)
                    request = ""
                    soc = ""
                    card_details_response = ""
                    gp_details = ""
                    template = ""
                    specs = ""
                    billing_address_data = ""
                    if incomplete_sub.request:
                        request = json.loads(incomplete_sub.request)
                    if incomplete_sub.specs:
                        specs = json.loads(incomplete_sub.specs)
                    if incomplete_sub.stripe_onetime_charge:
                        soc = json.loads(incomplete_sub.stripe_onetime_charge)
                    if incomplete_sub.gp_details:
                        gp_details = json.loads(incomplete_sub.gp_details)
                    if incomplete_sub.card_details_response:
                        card_details_response = json.loads(
                            incomplete_sub.card_details_response)
                    if incomplete_sub.template:
                        template = json.loads(
                            incomplete_sub.template)
                    if incomplete_sub.billing_address_data:
                        billing_address_data = json.loads(
                            incomplete_sub.billing_address_data)
                    logger.debug("*******")
                    logger.debug(str(incomplete_sub))
                    logger.debug("*******")
                    logger.debug("1*******")
                    logger.debug(request)
                    logger.debug("2*******")
                    logger.debug(card_details_response)
                    logger.debug("3*******")
                    logger.debug(soc)
                    logger.debug("4*******")
                    logger.debug(gp_details)
                    logger.debug("5*******")
                    logger.debug(template)
                    logger.debug("6*******")
                    do_provisioning(
                        request=request,
                        stripe_api_cus_id=incomplete_sub.stripe_api_cus_id,
                        card_details_response=card_details_response,
                        stripe_subscription_obj=stripe_subscription_obj,
                        stripe_onetime_charge=soc,
                        gp_details=gp_details,
                        specs=specs,
                        vm_template_id=incomplete_sub.vm_template_id,
                        template=template,
                        billing_address_data=billing_address_data,
                        real_request=None
                    )
                except (IncompleteSubscriptions.DoesNotExist,
                        IncompleteSubscriptions.MultipleObjectsReturned) as ex:
                    logger.error(str(ex))
                    email_data = {
                        'subject': "IncompleteSubscriptions error",
                        'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
                        'to': settings.DCL_ERROR_EMAILS_TO_LIST,
                        'body': "Response = %s" % str(ex),
                    }
                    send_plain_email_task.delay(email_data)
            except Exception as ex:
                logger.error(str(ex))
                email_data = {
                    'subject': "invoice.paid Webhook error",
                    'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
                    'to': settings.DCL_ERROR_EMAILS_TO_LIST,
                    'body': "Response = %s" % str(ex),
                }
                send_plain_email_task.delay(email_data)
    elif event.type == 'invoice.payment_failed':
        invoice_obj = event.data.object
        logger.debug("Webhook Event: invoice.payment_failed")
        logger.debug("invoice_obj %s " % str(invoice_obj))
        if (invoice_obj.payment_failed and
                invoice_obj.billing_reason == "subscription_update"):
            logger.debug("Payment failed, inform the users")
    elif event.type == 'payment_intent.succeeded':
        payment_intent_obj = event.data.object
        logger.debug("Webhook Event: payment_intent.succeeded")
        logger.debug("payment_intent_obj %s " % str(payment_intent_obj))

        try:
            incomplete_pm = IncompletePaymentIntents.objects.get(
                payment_intent_id=payment_intent_obj.id)
            request = ""
            soc = ""
            card_details_response = ""
            gp_details = ""
            template = ""
            billing_address_data = ""
            if incomplete_pm.request:
                request = json.loads(incomplete_pm.request)
            if incomplete_pm.stripe_onetime_charge:
                soc = json.loads(incomplete_pm.stripe_onetime_charge)
            if incomplete_pm.gp_details:
                gp_details = json.loads(incomplete_pm.gp_details)
            if incomplete_pm.card_details_response:
                card_details_response = json.loads(
                    incomplete_pm.card_details_response)
            if incomplete_pm.billing_address_data:
                billing_address_data = json.loads(
                    incomplete_pm.billing_address_data)
            logger.debug("1*******")
            logger.debug(request)
            logger.debug("2*******")
            logger.debug(card_details_response)
            logger.debug("3*******")
            logger.debug(soc)
            logger.debug("4*******")
            logger.debug(gp_details)
            logger.debug("5*******")
            logger.debug(template)
            logger.debug("6*******")
            logger.debug(billing_address_data)
            do_provisioning_generic(
                request=request,
                stripe_api_cus_id=incomplete_pm.stripe_api_cus_id,
                card_details_response=card_details_response,
                stripe_subscription_id=None,
                stripe_charge_id=soc,
                gp_details=gp_details,
                billing_address_data=billing_address_data
            )
        except (IncompletePaymentIntents.DoesNotExist,
                IncompletePaymentIntents.MultipleObjectsReturned) as ex:
            logger.error(str(ex))
            email_data = {
                'subject': "IncompletePaymentIntents error",
                'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
                'to': settings.DCL_ERROR_EMAILS_TO_LIST,
                'body': "Response = %s" % str(ex),
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