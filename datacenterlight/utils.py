import datetime
import logging

import pyotp
import requests
import stripe
from django.conf import settings
from django.contrib.sites.models import Site

from datacenterlight.tasks import create_vm_task
from hosting.models import HostingOrder, HostingBill, OrderDetail
from membership.models import StripeCustomer
from utils.forms import UserBillingAddressForm
from utils.models import BillingAddress, UserBillingAddress
from utils.stripe_utils import StripeUtils
from .cms_models import CMSIntegration
from .models import VMPricing, VMTemplate

logger = logging.getLogger(__name__)

eu_countries = ['at', 'be', 'bg', 'ch', 'cy', 'cz', 'hr', 'dk',
                'ee', 'fi', 'fr', 'mc', 'de', 'gr', 'hu', 'ie', 'it',
                'lv', 'lu', 'mt', 'nl', 'po', 'pt', 'ro','sk', 'si', 'es',
                'se', 'gb']


def get_cms_integration(name):
    current_site = Site.objects.get_current()
    try:
        cms_integration = CMSIntegration.objects.get(
            name=name, domain=current_site
        )
    except CMSIntegration.DoesNotExist:
        cms_integration = CMSIntegration.objects.get(name=name, domain=None)
    return cms_integration


def create_vm(billing_address_data, stripe_customer_id, specs,
              stripe_subscription_obj, card_details_dict, request,
              vm_template_id, template, user):
    billing_address = BillingAddress(
        cardholder_name=billing_address_data['cardholder_name'],
        street_address=billing_address_data['street_address'],
        city=billing_address_data['city'],
        postal_code=billing_address_data['postal_code'],
        country=billing_address_data['country'],
        vat_number=billing_address_data['vat_number'],
    )
    billing_address.save()
    customer = StripeCustomer.objects.filter(id=stripe_customer_id).first()
    vm_pricing = (
        VMPricing.get_vm_pricing_by_name(name=specs['pricing_name'])
        if 'pricing_name' in specs else
        VMPricing.get_default_pricing()
    )

    final_price = (
        specs.get('total_price')
        if 'total_price' in specs
        else specs.get('price')
    )

    # Create a Hosting Order with vm_id = 0, we shall set it later in
    # celery task once the VM instance is up and running
    order = HostingOrder.create(
        price=final_price,
        customer=customer,
        billing_address=billing_address,
        vm_pricing=vm_pricing
    )

    order_detail_obj, obj_created = OrderDetail.objects.get_or_create(
        vm_template=VMTemplate.objects.get(
            opennebula_vm_template_id=vm_template_id
        ),
        cores=specs['cpu'], memory=specs['memory'], ssd_size=specs['disk_size']
    )
    order.order_detail = order_detail_obj
    order.save()

    # Create a Hosting Bill
    HostingBill.create(customer=customer, billing_address=billing_address)

    # Create Billing Address for User if he does not have one
    if not customer.user.billing_addresses.count():
        billing_address_data.update({
            'user': customer.user.id
        })
        billing_address_user_form = UserBillingAddressForm(
            billing_address_data
        )
        billing_address_user_form.is_valid()
        billing_address_user_form.save()

    # Associate the given stripe subscription with the order
    order.set_subscription_id(
        stripe_subscription_obj.id, card_details_dict
    )

    # Set order status approved
    order.set_approved()

    create_vm_task.delay(vm_template_id, user, specs, template, order.id)

    clear_all_session_vars(request)


def clear_all_session_vars(request):
    if request.session is not None:
        for session_var in ['specs', 'template', 'billing_address',
                            'billing_address_data', 'card_id',
                            'token', 'customer', 'generic_payment_type',
                            'generic_payment_details', 'product_id',
                            'order_confirm_url', 'new_user_hosting_key_id',
                            'vat_validation_status', 'billing_address_id']:
            if session_var in request.session:
                del request.session[session_var]


def check_otp(name, realm, token):
    data = {
        "auth_name": settings.AUTH_NAME,
        "auth_token": pyotp.TOTP(settings.AUTH_SEED).now(),
        "auth_realm": settings.AUTH_REALM,
        "name": name,
        "realm": realm,
        "token": token
    }
    response = requests.post(
        "https://{OTP_SERVER}{OTP_VERIFY_ENDPOINT}".format(
            OTP_SERVER=settings.OTP_SERVER,
            OTP_VERIFY_ENDPOINT=settings.OTP_VERIFY_ENDPOINT
        ),
        data=data
    )
    return response.status_code


def validate_vat_number(stripe_customer_id, billing_address_id,
                        is_user_ba=False):
    if is_user_ba:
        try:
            billing_address = UserBillingAddress.objects.get(
                id=billing_address_id)
        except UserBillingAddress.DoesNotExist as dne:
            billing_address = None
            logger.debug(
                "UserBillingAddress does not exist for %s" % billing_address_id)
        except UserBillingAddress.MultipleObjectsReturned as mor:
            logger.debug(
                "Multiple UserBillingAddress exist for %s" % billing_address_id)
            billing_address = UserBillingAddress.objects.filter(
                id=billing_address_id).order_by('-id').first()
    else:
        try:
            billing_address = BillingAddress.objects.get(id=billing_address_id)
        except BillingAddress.DoesNotExist as dne:
            billing_address = None
            logger.debug("BillingAddress does not exist for %s" % billing_address_id)
        except BillingAddress.MultipleObjectsReturned as mor:
            logger.debug("Multiple BillingAddress exist for %s" % billing_address_id)
            billing_address = BillingAddress.objects.filter(id=billing_address_id).order_by('-id').first()
    if billing_address is not None:
        logger.debug("BillingAddress found: %s %s type=%s" % (
            billing_address_id, str(billing_address), type(billing_address)))
        if billing_address.country.lower().strip() not in eu_countries:
            return {
                "validated_on": "",
                "status": "not_needed"
            }
        if billing_address.vat_number_validated_on:
            logger.debug("billing_address verified on %s" %
                         billing_address.vat_number_validated_on)
            return {
                "validated_on": billing_address.vat_number_validated_on,
                "status": "verified"
            }
        else:
            logger.debug("billing_address not yet verified, "
                         "Checking if we already have a tax id")
            if billing_address.stripe_tax_id:
                logger.debug("We have a tax id %s" % billing_address.stripe_tax_id)
                tax_id_obj = stripe.Customer.retrieve_tax_id(
                  stripe_customer_id,
                  billing_address.stripe_tax_id,
                )
                if tax_id_obj.verification.status == "verified":
                    logger.debug("Latest status on Stripe=%s. Updating" %
                                 tax_id_obj.verification.status)
                    # update billing address
                    billing_address.vat_number_validated_on = datetime.datetime.now()
                    billing_address.vat_validation_status = tax_id_obj.verification.status
                    billing_address.save()
                    return {
                        "status": "verified",
                        "validated_on": billing_address.vat_number_validated_on
                    }
                else:
                    billing_address.vat_validation_status = tax_id_obj.verification.status
                    billing_address.save()
                    logger.debug(
                        "Latest status on Stripe=%s" % str(tax_id_obj)
                    )
                    return {
                        "status": tax_id_obj.verification.status if tax_id_obj
                        else "unknown",
                        "validated_on": ""
                    }
            else:
                logger.debug("Creating a tax id")
                logger.debug("Billing address = %s" % str(billing_address))
                tax_id_obj = create_tax_id(
                    stripe_customer_id, billing_address_id,
                    "ch_vat" if billing_address.country.lower() == "ch" else "eu_vat",
                    is_user_ba=is_user_ba
                )
                logger.debug("tax_id_obj = %s" % str(tax_id_obj))
    else:
        logger.debug("invalid billing address")
        return {
            "status": "invalid billing address",
            "validated_on": ""
        }

    if 'response_object' in tax_id_obj:
        return tax_id_obj

    return {
        "status": tax_id_obj.verification.status,
        "validated_on": datetime.datetime.now() if tax_id_obj.verification.status == "verified" else ""
    }


def create_tax_id(stripe_customer_id, billing_address_id, type,
                  is_user_ba=False):
    if is_user_ba:
        try:
            billing_address = UserBillingAddress.objects.get(
                id=billing_address_id)
        except UserBillingAddress.DoesNotExist as dne:
            billing_address = None
            logger.debug(
                "UserBillingAddress does not exist for %s" % billing_address_id)
        except UserBillingAddress.MultipleObjectsReturned as mor:
            logger.debug(
                "Multiple UserBillingAddress exist for %s" % billing_address_id)
            billing_address = UserBillingAddress.objects.filter(
                id=billing_address_id).order_by('-id').first()
    else:
        try:
            billing_address = BillingAddress.objects.get(id=billing_address_id)
        except BillingAddress.DoesNotExist as dne:
            billing_address = None
            logger.debug("BillingAddress does not exist for %s" % billing_address_id)
        except BillingAddress.MultipleObjectsReturned as mor:
            logger.debug("Multiple BillingAddress exist for %s" % billing_address_id)
            billing_address = BillingAddress.objects.filter(billing_address_id).order_by('-id').first()

    tax_id_obj = None
    if billing_address:
        stripe_utils = StripeUtils()
        tax_id_response = stripe_utils.get_or_create_tax_id_for_user(
            stripe_customer_id,
            vat_number=billing_address.vat_number,
            type=type,
            country=billing_address.country
        )

        tax_id_obj = tax_id_response.get('response_object')

    if not tax_id_obj:
        logger.debug("Received none in tax_id_obj")
        return {
            'paid': False,
            'response_object': None,
            'error': "No such address found" if 'error' not in tax_id_response else
            tax_id_response["error"]
        }

    try:
        stripe_customer = StripeCustomer.objects.get(stripe_id=stripe_customer_id)
        billing_address_set = set()
        logger.debug("Updating billing address")
        for ho in stripe_customer.hostingorder_set.all():
            if ho.billing_address.vat_number == billing_address.vat_number:
                billing_address_set.add(ho.billing_address)
        for b_address in billing_address_set:
            b_address.stripe_tax_id = tax_id_obj.id
            b_address.vat_validation_status = tax_id_obj.verification.status
            b_address.save()
            logger.debug("Updated billing_address %s" % str(b_address))

        ub_addresses = stripe_customer.user.billing_addresses.filter(
            vat_number=billing_address.vat_number)
        for ub_address in ub_addresses:
            ub_address.stripe_tax_id = tax_id_obj.id
            ub_address.vat_validation_status = tax_id_obj.verification.status
            ub_address.save()
            logger.debug("Updated user_billing_address %s" % str(ub_address))
    except StripeCustomer.DoesNotExist as dne:
        logger.debug("StripeCustomer %s does not exist" % stripe_customer_id)
        billing_address.stripe_tax_id = tax_id_obj.id
        billing_address.vat_validation_status = tax_id_obj.verification.status
        billing_address.save()
    return tax_id_obj
