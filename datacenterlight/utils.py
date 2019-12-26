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


def validate_vat_number(stripe_customer_id, billing_address_id):
    try:
        billing_address = BillingAddress.objects.get(id=billing_address_id)
    except BillingAddress.DoesNotExist as dne:
        billing_address = None
        logger.debug("BillingAddress does not exist for %s" % billing_address_id)
    except BillingAddress.MultipleObjectsReturned as mor:
        logger.debug("Multiple BillingAddress exist for %s" % billing_address_id)
        billing_address = BillingAddress.objects.filter(billing_address_id).order_by('-id').first()
    if billing_address is not None:
        if billing_address.vat_number_validated_on:
            return {
                "validated_on": billing_address.vat_number_validated_on,
                "status": "verified"
            }
        else:
            if billing_address.stripe_tax_id:
                tax_id_obj = stripe.Customer.retrieve_tax_id(
                  stripe_customer_id,
                  billing_address.stripe_tax_id,
                )
                if tax_id_obj.verification.status == "verified":
                    # update billing address
                    billing_address.vat_number_validated_on = datetime.datetime.now()
                    billing_address.save()
                    return {
                        "status": "verified",
                        "validated_on": billing_address.vat_number_validated_on
                    }
                else:
                    return {
                        "status": tax_id_obj.verification.status,
                        "validated_on": ""
                    }
            else:
                tax_id_obj = create_tax_id(
                    stripe_customer_id, billing_address.vat_number,
                    "ch_vat" if billing_address.country.lower() == "ch" else "eu_vat")
    else:
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


def create_tax_id(stripe_customer_id, vat_number, type):
    stripe_utils = StripeUtils()
    tax_id_response = stripe_utils.create_tax_id_for_user(
        stripe_customer_id,
        vat_number=vat_number,
        type=type
    )

    tax_id_obj = tax_id_response.get('response_object')

    if not tax_id_obj:
        return tax_id_response

    stripe_customer = StripeCustomer.objects.get(stripe_customer_id)
    billing_address_set = set()
    for ho in stripe_customer.hostingorder_set.all():
        if ho.billing_address.vat_number==vat_number:
            billing_address_set.add(ho.billing_address)
    for b_address in billing_address_set:
        b_address.stripe_tax_id = tax_id_obj.id

    ub_addresses = stripe_customer.user.billing_addresses.filter(
        vat_number=vat_number)
    for ub_address in ub_addresses:
        ub_address.stripe_tax_id = tax_id_obj.id
    return tax_id_obj
