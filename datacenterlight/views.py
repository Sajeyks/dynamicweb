import json
import logging

import stripe
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, authenticate
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, JsonResponse, Http404, \
    HttpResponse
from django.shortcuts import render
from django.utils.translation import get_language, ugettext_lazy as _
from django.views.decorators.cache import cache_control
from django.views.generic import FormView, CreateView, DetailView

from hosting.forms import (
    HostingUserLoginForm, GenericPaymentForm, ProductPaymentForm,
    UserHostingKeyForm
)
from hosting.models import (
    HostingBill, HostingOrder, UserCardDetail, GenericProduct, UserHostingKey,
    StripeTaxRate, IncompleteSubscriptions, IncompletePaymentIntents)
from membership.models import CustomUser, StripeCustomer
from opennebula_api.serializers import VMTemplateSerializer
from utils.forms import (
    BillingAddressForm, BillingAddressFormSignup, UserBillingAddressForm,
    BillingAddress
)
from utils.hosting_utils import (
    get_vm_price_with_vat, get_all_public_keys, get_vat_rate_for_country,
    get_vm_price_for_given_vat
)
from utils.stripe_utils import StripeUtils
from utils.tasks import send_plain_email_task
from .cms_models import DCLCalculatorPluginModel
from .forms import ContactForm
from .models import VMTemplate, VMPricing
from .utils import (
    get_cms_integration, create_vm, clear_all_session_vars, validate_vat_number
)

logger = logging.getLogger(__name__)


class ContactUsView(FormView):
    template_name = "datacenterlight/contact_form.html"
    form_class = ContactForm

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(reverse('datacenterlight:index'))

    def form_invalid(self, form):
        if self.request.is_ajax():
            return self.render_to_response(
                self.get_context_data(contact_form=form))
        else:
            return render(
                self.request, 'datacenterlight/index.html',
                self.get_context_data(contact_form=form)
            )

    def form_valid(self, form):
        form.save()
        from_emails = {
            'glasfaser': 'glasfaser@ungleich.ch'
        }
        from_page = self.request.POST.get('from_page')
        email_data = {
            'subject': "{dcl_text} Message from {sender}".format(
                dcl_text=settings.DCL_TEXT,
                sender=form.cleaned_data.get('email')
            ),
            'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
            'to': [from_emails.get(from_page, 'support@ungleich.ch')],
            'body': "\n".join(
                ["%s=%s" % (k, v) for (k, v) in form.cleaned_data.items()]),
            'reply_to': [form.cleaned_data.get('email')],
        }
        send_plain_email_task.delay(email_data)
        if self.request.is_ajax():
            return self.render_to_response(
                self.get_context_data(success=True, contact_form=form))
        else:
            return render(
                self.request, 'datacenterlight/index.html',
                self.get_context_data(success=True, contact_form=form)
            )


class IndexView(CreateView):
    template_name = "datacenterlight/index.html"
    success_url = "/datacenterlight#requestform"
    success_message = "Thank you, we will contact you as soon as possible"

    def validate_cores(self, value):
        if (value > 48) or (value < 1):
            raise ValidationError(_('Invalid number of cores'))

    def validate_memory(self, value):
        if 'pid' in self.request.POST:
            try:
                plugin = DCLCalculatorPluginModel.objects.get(
                             id=self.request.POST['pid']
                         )
            except DCLCalculatorPluginModel.DoesNotExist as dne:
                logger.error(
                    str(dne) + " plugin_id: " + self.request.POST['pid']
                )
                raise ValidationError(_('Invalid calculator properties'))
            if plugin.enable_512mb_ram:
                if value % 1 == 0 or value == 0.5:
                    logger.debug(
                        "Given ram {value} is either 0.5 or a"
                        " whole number".format(value=value)
                    )
                    if (value > 200) or (value < 0.5):
                        raise ValidationError(_('Invalid RAM size'))
                else:
                    raise ValidationError(_('Invalid RAM size'))
            elif (value > 200) or (value < 1) or (value % 1 != 0):
                raise ValidationError(_('Invalid RAM size'))
        else:
            raise ValidationError(_('Invalid RAM size'))

    def validate_storage(self, value):
        if (value > 2000) or (value < 10):
            raise ValidationError(_('Invalid storage size'))

    @cache_control(no_cache=True, must_revalidate=True, no_store=True)
    def get(self, request, *args, **kwargs):
        clear_all_session_vars(request)
        return HttpResponseRedirect(reverse('datacenterlight:cms_index'))

    def post(self, request):
        cores = request.POST.get('cpu')
        cores_field = forms.IntegerField(validators=[self.validate_cores])
        memory = request.POST.get('ram')
        memory_field = forms.FloatField(validators=[self.validate_memory])
        storage = request.POST.get('storage')
        storage_field = forms.IntegerField(validators=[self.validate_storage])
        template_id = int(request.POST.get('config'))
        pricing_name = request.POST.get('pricing_name')
        vm_pricing = VMPricing.get_vm_pricing_by_name(pricing_name)

        template = VMTemplate.objects.filter(
            opennebula_vm_template_id=template_id
        ).first()
        template_data = VMTemplateSerializer(template).data
        referer_url = request.META['HTTP_REFERER']

        if vm_pricing is None:
            vm_pricing_name_msg = _(
                "Incorrect pricing name. Please contact support"
                "{support_email}".format(
                    support_email=settings.DCL_SUPPORT_FROM_ADDRESS
                )
            )
            messages.add_message(
                self.request, messages.ERROR, vm_pricing_name_msg,
                extra_tags='pricing'
            )
            return HttpResponseRedirect(referer_url + "#order_form")
        else:
            vm_pricing_name = vm_pricing.name

        try:
            cores = cores_field.clean(cores)
        except ValidationError as err:
            msg = '{} : {}.'.format(cores, str(err))
            messages.add_message(
                self.request, messages.ERROR, msg, extra_tags='cores'
            )
            return HttpResponseRedirect(referer_url + "#order_form")

        try:
            memory = memory_field.clean(memory)
        except ValidationError as err:
            msg = '{} : {}.'.format(memory, str(err))
            messages.add_message(
                self.request, messages.ERROR, msg, extra_tags='memory'
            )
            return HttpResponseRedirect(referer_url + "#order_form")

        try:
            storage = storage_field.clean(storage)
        except ValidationError as err:
            msg = '{} : {}.'.format(storage, str(err))
            messages.add_message(
                self.request, messages.ERROR, msg, extra_tags='storage'
            )
            return HttpResponseRedirect(referer_url + "#order_form")

        price, vat, vat_percent, discount = get_vm_price_with_vat(
            cpu=cores,
            memory=memory,
            ssd_size=storage,
            pricing_name=vm_pricing_name
        )
        specs = {
            'cpu': cores,
            'memory': memory,
            'disk_size': storage,
            'price': price,
            'vat': vat,
            'vat_percent': vat_percent,
            'discount': discount,
            'total_price': round(price + vat - discount['amount'], 2),
            'pricing_name': vm_pricing_name
        }
        request.session['specs'] = specs
        request.session['template'] = template_data
        return HttpResponseRedirect(reverse('datacenterlight:payment'))

    def get_success_url(self):
        success_url = reverse('datacenterlight:index')
        success_url += "#requestform"
        return success_url

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        context.update({
            'base_url': "{0}://{1}".format(
                self.request.scheme, self.request.get_host()
            ),
            'contact_form': ContactForm
        })
        return context


class WhyDataCenterLightView(IndexView):
    template_name = "datacenterlight/whydatacenterlight.html"


class PaymentOrderView(FormView):
    template_name = 'datacenterlight/landing_payment.html'

    def get_form_class(self):
        if self.request.user.is_authenticated():
            return BillingAddressForm
        else:
            return BillingAddressFormSignup

    def get_context_data(self, **kwargs):
        context = super(PaymentOrderView, self).get_context_data(**kwargs)
        if 'billing_address_data' in self.request.session:
            billing_address_data = self.request.session['billing_address_data']
        else:
            billing_address_data = {}

        if self.request.user.is_authenticated():
            if billing_address_data:
                billing_address_form = BillingAddressForm(
                    initial=billing_address_data
                )
            else:
                billing_address_form = BillingAddressForm(
                    instance=self.request.user.billing_addresses.order_by('-id').first()
                )
            user = self.request.user
            if hasattr(user, 'stripecustomer'):
                stripe_customer = user.stripecustomer
            else:
                stripe_customer = None
            cards_list = UserCardDetail.get_all_cards_list(
                stripe_customer=stripe_customer
            )
            context.update({'cards_list': cards_list})
        else:
            billing_address_form = BillingAddressFormSignup(
                initial=billing_address_data
            )

        context.update({
            'stripe_key': settings.STRIPE_API_PUBLIC_KEY,
            'site_url': reverse('datacenterlight:index'),
            'login_form': HostingUserLoginForm(prefix='login_form'),
            'billing_address_form': billing_address_form,
            'cms_integration': get_cms_integration('default'),
        })

        if ('generic_payment_type' in self.request.session and
                self.request.session['generic_payment_type'] == 'generic'):
            if 'product_id' in self.request.session:
                product = GenericProduct.objects.get(
                    id=self.request.session['product_id']
                )
                context.update({'generic_payment_form': ProductPaymentForm(
                    prefix='generic_payment_form',
                    initial={'product_name': product.product_name,
                             'amount': float(product.get_actual_price()),
                             'recurring': product.product_is_subscription,
                             'description': product.product_description,
                             },
                    product_id=product.id
                ), })
            else:
                context.update({'generic_payment_form': GenericPaymentForm(
                    prefix='generic_payment_form',
                ), })
        else:
            context.update({
                'vm_pricing': VMPricing.get_vm_pricing_by_name(
                    self.request.session['specs']['pricing_name']
                )
            })

        return context

    @cache_control(no_cache=True, must_revalidate=True, no_store=True)
    def get(self, request, *args, **kwargs):
        request.session.pop('vat_validation_status')
        request.session.pop('card_id')
        request.session.pop('token')
        request.session.pop('id_payment_method')
        logger.debug("Session: %s" % str(request.session))
        for key, value in request.session.items():
            logger.debug("Session: %s %s" % (key, value))
        if (('type' in request.GET and request.GET['type'] == 'generic')
                or 'product_slug' in kwargs):
            request.session['generic_payment_type'] = 'generic'
            if 'generic_payment_details' in request.session:
                request.session.pop('generic_payment_details')
                request.session.pop('product_id')
            if 'product_slug' in kwargs:
                logger.debug("Product slug is " + kwargs['product_slug'])
                try:
                    product = GenericProduct.objects.get(
                        product_slug=kwargs['product_slug']
                    )
                except GenericProduct.DoesNotExist as dne:
                    logger.error(
                        "Product '{}' does "
                        "not exist".format(kwargs['product_slug'])
                    )
                    raise Http404()
                request.session['product_id'] = product.id
        elif 'specs' not in request.session:
            return HttpResponseRedirect(reverse('datacenterlight:index'))
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        if 'product' in request.POST:
            # query for the supplied product
            product = None
            try:
                product = GenericProduct.objects.get(
                    id=request.POST['generic_payment_form-product_name']
                )
            except GenericProduct.DoesNotExist as dne:
                logger.error(
                    "The requested product '{}' does not exist".format(
                        request.POST['generic_payment_form-product_name']
                    )
                )
            except GenericProduct.MultipleObjectsReturned as mpe:
                logger.error(
                    "There seem to be more than one product with "
                    "the name {}".format(
                        request.POST['generic_payment_form-product_name']
                    )
                )
                product = GenericProduct.objects.all(
                    product_name=request.
                    POST['generic_payment_form-product_name']
                ).first()
            if product is None:
                return JsonResponse({})
            else:
                return JsonResponse({
                    'amount': product.get_actual_price(),
                    'isSubscription': product.product_is_subscription
                })
        if 'login_form' in request.POST:
            login_form = HostingUserLoginForm(
                data=request.POST, prefix='login_form'
            )
            if login_form.is_valid():
                email = login_form.cleaned_data.get('email')
                password = login_form.cleaned_data.get('password')
                auth_user = authenticate(email=email, password=password)
                if auth_user:
                    login(self.request, auth_user)
                    if 'product_slug' in kwargs:
                        return HttpResponseRedirect(
                            reverse('show_product',
                                    kwargs={
                                        'product_slug': kwargs['product_slug']}
                                    )
                        )
                    return HttpResponseRedirect(
                        reverse('datacenterlight:payment')
                    )
            else:
                context = self.get_context_data()
                context['login_form'] = login_form
                return self.render_to_response(context)
        if request.user.is_authenticated():
            address_form = BillingAddressForm(
                data=request.POST,
            )
        else:
            address_form = BillingAddressFormSignup(
                data=request.POST,
            )
        if address_form.is_valid():
            # Check if we are in a generic payment case and handle the generic
            # payment details form before we go on to verify payment
            if ('generic_payment_type' in request.session and
                    self.request.session['generic_payment_type'] == 'generic'):
                if 'product_id' in request.session:
                    generic_payment_form = ProductPaymentForm(
                        data=request.POST, prefix='generic_payment_form',
                        product_id=request.session['product_id']
                    )
                else:
                    generic_payment_form = GenericPaymentForm(
                        data=request.POST, prefix='generic_payment_form'
                    )
                if generic_payment_form.is_valid():
                    logger.debug("Generic payment form is valid.")
                    if 'product_id' in request.session:
                        product = generic_payment_form.product
                    else:
                        product = generic_payment_form.cleaned_data.get(
                            'product_name'
                        )
                    user_country_vat_rate = get_vat_rate_for_country(
                        address_form.cleaned_data["country"]
                    )
                    gp_details = {
                        "product_name": product.product_name,
                        "vat_rate": 0 if product.exclude_vat_calculations else
                        user_country_vat_rate * 100,
                        "vat_amount": 0 if product.exclude_vat_calculations
                        else round(
                            float(product.product_price) *
                            user_country_vat_rate, 2),
                        "vat_country": address_form.cleaned_data["country"],
                        "amount_before_vat": round(
                            float(product.product_price), 2),
                        "amount": product.get_actual_price(
                            vat_rate=get_vat_rate_for_country(
                                address_form.cleaned_data["country"])
                        ),
                        "recurring": generic_payment_form.cleaned_data.get(
                            'recurring'
                        ),
                        "description": generic_payment_form.cleaned_data.get(
                            'description'
                        ),
                        "product_id": product.id,
                        "product_slug": product.product_slug,
                        "recurring_interval":
                            product.product_subscription_interval,
                        "exclude_vat_calculations": product.exclude_vat_calculations
                    }
                    request.session["generic_payment_details"] = (
                        gp_details
                    )
                else:
                    logger.debug("Generic payment form invalid")
                    context = self.get_context_data()
                    context['generic_payment_form'] = generic_payment_form
                    context['billing_address_form'] = address_form
                    return self.render_to_response(context)
            id_payment_method = self.request.POST.get('id_payment_method',
                                                      None)
            if id_payment_method is None:
                card_id = address_form.cleaned_data.get('card')
                logger.debug("token is empty and card_id is %s" % card_id)
                try:
                    user_card_detail = UserCardDetail.objects.get(id=card_id)
                    if not request.user.has_perm(
                            'view_usercarddetail', user_card_detail
                    ):
                        raise UserCardDetail.DoesNotExist(
                            _("{user} does not have permission to access the "
                              "card").format(user=request.user.email)
                        )
                except UserCardDetail.DoesNotExist as e:
                    ex = str(e)
                    logger.error("Card Id: {card_id}, Exception: {ex}".format(
                        card_id=card_id, ex=ex
                    )
                    )
                    msg = _("An error occurred. Details: {}".format(ex))
                    messages.add_message(
                        self.request, messages.ERROR, msg,
                        extra_tags='make_charge_error'
                    )
                    return HttpResponseRedirect(
                        reverse('datacenterlight:payment') + '#payment_error'
                    )
                request.session['card_id'] = user_card_detail.id
            else:
                request.session["id_payment_method"] = id_payment_method
                logger.debug("id_payment_method is %s" % id_payment_method)
            if request.user.is_authenticated():
                this_user = {
                    'email': request.user.email,
                    'name': request.user.name
                }
                customer = StripeCustomer.get_or_create(
                    email=this_user.get('email'),
                    id_payment_method=id_payment_method
                )
            else:
                user_email = address_form.cleaned_data.get('email')
                user_name = address_form.cleaned_data.get('name')
                this_user = {
                    'email': user_email,
                    'name': user_name
                }
                try:
                    custom_user = CustomUser.objects.get(email=user_email)
                    customer = StripeCustomer.objects.filter(
                        user_id=custom_user.id).first()
                    if customer is None:
                        logger.debug(
                            ("User {email} is already registered with us."
                             "But, StripeCustomer does not exist for {email}."
                             "Hence, creating a new StripeCustomer.").format(
                                email=user_email
                            )
                        )
                        customer = StripeCustomer.create_stripe_api_customer(
                            email=user_email,
                            token=id_payment_method,
                            customer_name=user_name)
                except CustomUser.DoesNotExist:
                    logger.debug(
                        ("StripeCustomer does not exist for {email}."
                         "Hence, creating a new StripeCustomer.").format(
                            email=user_email
                        )
                    )
                    customer = StripeCustomer.create_stripe_api_customer(
                        email=user_email,
                        token=id_payment_method,
                        customer_name=user_name)

            billing_address = address_form.save()
            request.session["billing_address_id"] = billing_address.id
            request.session['billing_address_data'] = address_form.cleaned_data
            request.session['user'] = this_user
            # Get or create stripe customer
            if not customer:
                address_form.add_error(
                    "__all__", "Invalid credit card"
                )
                return self.render_to_response(
                    self.get_context_data(
                        billing_address_form=address_form
                    )
                )
            if type(customer) is StripeCustomer:
                request.session['customer'] = customer.stripe_id
            else:
                request.session['customer'] = customer

            vat_number = address_form.cleaned_data.get('vat_number').strip()
            if vat_number:
                validate_result = validate_vat_number(
                    stripe_customer_id=request.session['customer'],
                    billing_address_id=billing_address.id
                )

                if 'error' in validate_result and validate_result['error']:
                    messages.add_message(
                        request, messages.ERROR, validate_result["error"],
                        extra_tags='vat_error'
                    )
                    return HttpResponseRedirect(
                        reverse('datacenterlight:payment') + '#vat_error'
                    )
                request.session["vat_validation_status"] = validate_result["status"]

            # For generic payment we take the user directly to confirmation
            if ('generic_payment_type' in request.session and
                    self.request.session['generic_payment_type'] == 'generic'):
                return HttpResponseRedirect(
                    reverse('datacenterlight:order_confirmation'))
            else:
                self.request.session['order_confirm_url'] = reverse('datacenterlight:order_confirmation')
                return HttpResponseRedirect(
                    reverse('datacenterlight:add_ssh_key'))
        else:
            context = self.get_context_data()
            context['billing_address_form'] = address_form
            return self.render_to_response(context)


class OrderConfirmationView(DetailView, FormView):
    form_class = UserHostingKeyForm
    template_name = "datacenterlight/order_detail.html"
    payment_template_name = 'datacenterlight/landing_payment.html'
    context_object_name = "order"
    model = HostingOrder

    def get_form_kwargs(self):
        kwargs = super(OrderConfirmationView, self).get_form_kwargs()
        kwargs.update({'request': self.request})
        return kwargs

    @cache_control(no_cache=True, must_revalidate=True, no_store=True)
    def get(self, request, *args, **kwargs):
        context = {}
        if (('specs' not in request.session or 'user' not in request.session)
                and 'generic_payment_type' not in request.session):
            return HttpResponseRedirect(reverse('datacenterlight:index'))
        if 'id_payment_method' in self.request.session:
            payment_method = self.request.session['id_payment_method']
            stripe_utils = StripeUtils()
            card_details = stripe_utils.get_cards_details_from_payment_method(
                payment_method
            )
            if not card_details.get('response_object'):
                return HttpResponseRedirect(reverse('hosting:payment'))
            card_details_response = card_details['response_object']
            context['cc_last4'] = card_details_response['last4']
            context['cc_brand'] = card_details_response['brand']
            context['cc_exp_year'] = card_details_response['exp_year']
            context['cc_exp_month'] = '{:02d}'.format(card_details_response['exp_month'])
            context['id_payment_method'] = payment_method
        else:
            card_id = self.request.session.get('card_id')
            card_detail = UserCardDetail.objects.get(id=card_id)
            context['cc_last4'] = card_detail.last4
            context['cc_brand'] = card_detail.brand
            context['cc_exp_year'] = card_detail.exp_year
            context['cc_exp_month'] ='{:02d}'.format(card_detail.exp_month)

        if ('generic_payment_type' in request.session and
                self.request.session['generic_payment_type'] == 'generic'):
            if "vat_validation_status" in request.session and (
                    request.session["vat_validation_status"] == "verified" or
                    request.session["vat_validation_status"] == "not_needed"):
                request.session['generic_payment_details']['vat_rate'] = 0
                request.session['generic_payment_details']['vat_amount'] = 0
                request.session['generic_payment_details']['amount'] = request.session['generic_payment_details']['amount_before_vat']
            context.update({
                'generic_payment_details':
                    request.session['generic_payment_details'],
            })
        else:
            vm_specs = request.session.get('specs')
            user_vat_country = (
                request.session.get('billing_address_data').get("country")
            )
            user_country_vat_rate = get_vat_rate_for_country(user_vat_country)
            price, vat, vat_percent, discount = get_vm_price_for_given_vat(
                cpu=vm_specs['cpu'],
                memory=vm_specs['memory'],
                ssd_size=vm_specs['disk_size'],
                pricing_name=vm_specs['pricing_name'],
                vat_rate=user_country_vat_rate * 100
            )
            vm_specs["price"] = price
            vm_specs["price_after_discount"] = price - discount["amount"]

            vat_number = request.session.get('billing_address_data').get("vat_number")
            billing_address = BillingAddress.objects.get(id=request.session["billing_address_id"])
            if vat_number:
                validate_result = validate_vat_number(
                    stripe_customer_id=request.session['customer'],
                    billing_address_id=billing_address.id
                )
                if 'error' in validate_result and validate_result['error']:
                    messages.add_message(
                        request, messages.ERROR, validate_result["error"],
                        extra_tags='vat_error'
                    )
                    return HttpResponseRedirect(
                        reverse('datacenterlight:payment') + '#vat_error'
                    )

                request.session["vat_validation_status"] = validate_result["status"]

            if user_vat_country.lower() == "ch":
                vm_specs["vat"] = vat
                vm_specs["vat_percent"] = vat_percent
                vm_specs["vat_validation_status"] = "ch_vat"
            elif ("vat_validation_status" in request.session and
                    (request.session["vat_validation_status"] == "verified" or
                     request.session["vat_validation_status"] == "not_needed")):
                vm_specs["vat_percent"] = 0
                vm_specs["vat"] = 0
                vm_specs["vat_validation_status"] = request.session["vat_validation_status"]
            else:
                vm_specs["vat"] = vat
                vm_specs["vat_percent"] = vat_percent
                vm_specs["vat_validation_status"] = request.session["vat_validation_status"] if "vat_validation_status" in request.session else ""
            vm_specs["vat_country"] = user_vat_country
            vm_specs["price_with_vat"] = round(price * (1 + vm_specs["vat_percent"] * 0.01), 2)
            vm_specs["price_after_discount"] = round(price - discount['amount'], 2)
            vm_specs["price_after_discount_with_vat"] = round((price - discount['amount']) * (1 + vm_specs["vat_percent"] * 0.01), 2)
            discount["amount_with_vat"] = round(vm_specs["price_with_vat"] - vm_specs["price_after_discount_with_vat"], 2)
            vm_specs["total_price"] = vm_specs["price_after_discount_with_vat"]
            vm_specs["discount"] = discount
            logger.debug(vm_specs)
            request.session['specs'] = vm_specs

            context.update({
                'vm': vm_specs,
                'form': UserHostingKeyForm(request=self.request),
                'keys': get_all_public_keys(self.request.user)
            })

        # Obtain PaymentIntent so that we can initiate and charge/subscribe
        # the customer
        stripe_utils = StripeUtils()
        payment_intent_response = stripe_utils.get_payment_intent(
            int(request.session['generic_payment_details']['amount'] *
                100),
            customer=request.session['customer']
        )
        payment_intent = payment_intent_response.get(
            'response_object')
        if not payment_intent:
            logger.error("Could not create payment_intent %s" %
                         str(payment_intent_response))
        else:
            logger.debug("payment_intent.client_secret = %s" %
                         str(payment_intent.client_secret))
        context.update({
            'payment_intent_secret': payment_intent.client_secret
        })

        context.update({
            'site_url': reverse('datacenterlight:index'),
            'page_header_text': _('Confirm Order'),
            'billing_address_data': (
                request.session.get('billing_address_data')
            ),
            'cms_integration': get_cms_integration('default'),
            'error_msg': get_error_response_dict("Error", request),
            'success_msg': {
                'msg_title': _("Thank you !"),
                'msg_body': _("Your product will be provisioned as soon as "
                                 "we receive the payment."),
                'redirect': reverse('hosting:invoices') if
                request.user.is_authenticated() else
                reverse('datacenterlight:index')
            },
            'stripe_key': settings.STRIPE_API_PUBLIC_KEY,
        })
        logger.debug("Request %s" % create_incomplete_intent_request(
            self.request))
        logger.debug("%s" % str(payment_intent))
        logger.debug("customer %s" % request.session['customer'])
        logger.debug("card_details_response %s" % card_details_response)
        logger.debug("request.session[generic_payment_details] %s" % request.session["generic_payment_details"])
        logger.debug("request.session[billing_address_data] %s" % request.session["billing_address_data"])
        IncompletePaymentIntents.objects.create(
            request=create_incomplete_intent_request(self.request),
            payment_intent_id=payment_intent.id,
            stripe_api_cus_id=request.session['customer'],
            card_details_response=json.dumps(card_details_response),
            stripe_subscription_id=None,
            stripe_charge_id=None,
            gp_details=json.dumps(request.session["generic_payment_details"]),
            billing_address_data=json.dumps(request.session["billing_address_data"])
        )
        logger.debug("IncompletePaymentIntent done")
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        stripe_onetime_charge = None
        stripe_customer_obj = None
        gp_details = None
        specs = None
        vm_template_id = 0
        template = None
        user = request.session.get('user')
        stripe_api_cus_id = request.session.get('customer')
        stripe_utils = StripeUtils()
        logger.debug("user=%s stripe_api_cus_id=%s" % (user, stripe_api_cus_id))
        card_details_response = None
        new_user_hosting_key_id = None
        card_id = None
        generic_payment_type = None
        generic_payment_details = None
        stripe_subscription_obj = None
        if 'generic_payment_details' in request.session:
            generic_payment_details = request.session[
                'generic_payment_details']
        if 'generic_payment_type' in request.session:
            generic_payment_type = request.session['generic_payment_type']
        if 'new_user_hosting_key_id' in self.request.session:
            new_user_hosting_key_id = request.session[
                'new_user_hosting_key_id']
        if 'card_id' in request.session:
            card_id = request.session.get('card_id')
        req = {
            'scheme': self.request.scheme,
            'host': self.request.get_host(),
            'language': get_language(),
            'new_user_hosting_key_id': new_user_hosting_key_id,
            'card_id': card_id,
            'generic_payment_type': generic_payment_type,
            'generic_payment_details': generic_payment_details
        }

        if 'id_payment_method' in request.session:
            card_details = stripe_utils.get_cards_details_from_payment_method(
                request.session.get('id_payment_method')
            )
            logger.debug(
                "card_details=%s" % (card_details))
            if not card_details.get('response_object'):
                msg = card_details.get('error')
                return show_error(msg, self.request)
            card_details_response = card_details['response_object']
            card_details_dict = {
                'last4': card_details_response['last4'],
                'brand': card_details_response['brand'],
                'card_id': card_details_response['card_id']
            }
            stripe_customer_obj = StripeCustomer.objects.filter(
                stripe_id=stripe_api_cus_id).first()
            if stripe_customer_obj:
                ucd = UserCardDetail.get_user_card_details(
                    stripe_customer_obj, card_details_response
                )
                if not ucd:
                    acc_result = stripe_utils.associate_customer_card(
                        stripe_api_cus_id, request.session['id_payment_method'],
                        set_as_default=True
                    )
                    if acc_result['response_object'] is None:
                        msg = _(
                            'An error occurred while associating the card.'
                            ' Details: {details}'.format(
                                details=acc_result['error']
                            )
                        )
                        return show_error(msg, self.request)
            else:
                # Associate PaymentMethod with the stripe customer
                # and set it as the default source
                acc_result = stripe_utils.associate_customer_card(
                    stripe_api_cus_id, request.session['id_payment_method'],
                    set_as_default=True
                )
                if acc_result['response_object'] is None:
                    msg = _(
                        'An error occurred while associating the card.'
                        ' Details: {details}'.format(
                            details=acc_result['error']
                        )
                    )
                    return show_error(msg, self.request)
        elif 'card_id' in request.session:
            card_id = request.session.get('card_id')
            user_card_detail = UserCardDetail.objects.get(id=card_id)
            card_details_dict = {
                'last4': user_card_detail.last4,
                'brand': user_card_detail.brand,
                'card_id': user_card_detail.card_id
            }
            UserCardDetail.set_default_card(
                stripe_api_cus_id=stripe_api_cus_id,
                stripe_source_id=user_card_detail.card_id
            )
            logger.debug("card_details_dict=%s" % card_details_dict)
        else:
            response = {
                'status': False,
                'redirect': "{url}#{section}".format(
                    url=reverse('datacenterlight:payment'),
                    section='payment_error'),
                'msg_title': str(_('Error.')),
                'msg_body': str(
                    _('There was a payment related error.'
                      ' On close of this popup, you will be redirected back to'
                      ' the payment page.'))
            }
            return JsonResponse(response)

        if ('generic_payment_type' in request.session and
                self.request.session['generic_payment_type'] == 'generic'):
            gp_details = self.request.session['generic_payment_details']
            logger.debug("gp_details=%s" % gp_details)
            if gp_details['recurring']:
                # generic recurring payment
                logger.debug("Commencing a generic recurring payment")
            else:
                # generic one time payment
                logger.debug("Commencing a one time payment")
                charge_response = stripe_utils.make_charge(
                    amount=gp_details['amount'],
                    customer=stripe_api_cus_id
                )
                stripe_onetime_charge = charge_response.get('response_object')
                # Check if the payment was approved
                if not stripe_onetime_charge:
                    msg = charge_response.get('error')
                    return show_error(msg, self.request)
        if ('generic_payment_type' not in request.session or
                (request.session['generic_payment_details']['recurring'])):
            recurring_interval = 'month'
            logger.debug("'generic_payment_type' not in request.session or"
                         "(request.session['generic_payment_details']['recurring']")
            if 'generic_payment_details' in request.session:
                vat_percent = request.session['generic_payment_details']['vat_rate']
                vat_country = request.session['generic_payment_details']['vat_country']
                if 'discount' in request.session['generic_payment_details']:
                    discount = request.session['generic_payment_details']['discount']
                else:
                    discount = {'name': '', 'amount': 0, 'coupon_id': ''}
                amount_to_be_charged = (
                    round(
                        request.session['generic_payment_details']['amount_before_vat'],
                        2
                    )
                )
                plan_name = "generic-{0}-{1:.2f}".format(
                    request.session['generic_payment_details']['product_id'],
                    amount_to_be_charged
                )
                stripe_plan_id = plan_name
                recurring_interval = request.session['generic_payment_details']['recurring_interval']
                if recurring_interval == "year":
                    plan_name = "{}-yearly".format(plan_name)
                    stripe_plan_id = plan_name
            else:
                template = request.session.get('template')
                specs = request.session.get('specs')
                vm_template_id = template.get('id', 1)

                cpu = specs.get('cpu')
                memory = specs.get('memory')
                disk_size = specs.get('disk_size')
                amount_to_be_charged = specs.get('price')
                vat_percent = specs.get('vat_percent')
                vat_country = specs.get('vat_country')
                discount = specs.get('discount')
                plan_name = StripeUtils.get_stripe_plan_name(
                    cpu=cpu,
                    memory=memory,
                    disk_size=disk_size,
                    price=amount_to_be_charged
                )
                stripe_plan_id = StripeUtils.get_stripe_plan_id(
                    cpu=cpu,
                    ram=memory,
                    ssd=disk_size,
                    version=1,
                    app='dcl',
                    price=amount_to_be_charged
                )
                logger.debug(specs)
            stripe_plan = stripe_utils.get_or_create_stripe_plan(
                amount=amount_to_be_charged,
                name=plan_name,
                stripe_plan_id=stripe_plan_id,
                interval=recurring_interval
            )
            # Create StripeTaxRate if applicable to the user
            logger.debug("vat_percent = %s, vat_country = %s" %
                (vat_percent, vat_country)
            )
            stripe_tax_rate = None
            if vat_percent > 0:
                try:
                    stripe_tax_rate = StripeTaxRate.objects.get(
                        description="VAT for %s" % vat_country
                    )
                    print("Stripe Tax Rate exists")
                except StripeTaxRate.DoesNotExist as dne:
                    print("StripeTaxRate does not exist")
                    tax_rate_obj = stripe.TaxRate.create(
                        display_name="VAT",
                        description="VAT for %s" % vat_country,
                        jurisdiction=vat_country,
                        percentage=vat_percent,
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
                    logger.debug("Created StripeTaxRate %s" %
                                 stripe_tax_rate.tax_rate_id)
            subscription_result = stripe_utils.subscribe_customer_to_plan(
                stripe_api_cus_id,
                [{"plan": stripe_plan.get('response_object').stripe_plan_id}],
                coupon=(discount['stripe_coupon_id']
                    if 'name' in discount and
                       discount['name'] is not None and
                       'ipv6' in discount['name'].lower() and
                       discount['stripe_coupon_id']
                    else ""),
                tax_rates=[stripe_tax_rate.tax_rate_id] if stripe_tax_rate else [],
            )
            stripe_subscription_obj = subscription_result.get('response_object')
            logger.debug(stripe_subscription_obj)
            latest_invoice = stripe.Invoice.retrieve(
                stripe_subscription_obj.latest_invoice)
            subscription_status = ''
            if stripe_subscription_obj:
                subscription_status = stripe_subscription_obj.status

            # Check if the subscription was approved and is active
            if (stripe_subscription_obj is None
                    or (stripe_subscription_obj.status != 'active'
                        and stripe_subscription_obj.status != 'incomplete')):
                # At this point, we have created a Stripe API card and
                # associated it with the customer; but the transaction failed
                # due to some reason. So, we would want to dissociate this card
                # here.
                # ...
                msg = subscription_result.get('error')
                return show_error(msg, self.request)
            elif stripe_subscription_obj.status == 'incomplete':
                # Store params so that they can be retrieved later
                IncompleteSubscriptions.objects.create(
                    subscription_id=stripe_subscription_obj.id,
                    subscription_status=subscription_status,
                    name=user.get('name'),
                    email=user.get('email'),
                    request=json.dumps(req),
                    stripe_api_cus_id=stripe_api_cus_id,
                    card_details_response=json.dumps(card_details_response),
                    stripe_subscription_obj=json.dumps(
                        stripe_subscription_obj) if stripe_customer_obj else '',
                    stripe_onetime_charge=json.dumps(
                        stripe_onetime_charge) if stripe_onetime_charge else '',
                    gp_details=json.dumps(gp_details) if gp_details else '',
                    specs=json.dumps(specs) if specs else '',
                    vm_template_id=vm_template_id if vm_template_id else 0,
                    template=json.dumps(template) if template else '',
                    billing_address_data=json.dumps(
                        request.session.get('billing_address_data')
                    )
                )
                pi = stripe.PaymentIntent.retrieve(
                    latest_invoice.payment_intent
                )
                # TODO: requires_attention is probably wrong value to compare
                if (pi.status == 'requires_attention' or
                        pi.status == 'requires_source_action'):
                    logger.debug("Display SCA authentication %s " % pi.status)
                    context = {
                        'sid': stripe_subscription_obj.id,
                        'payment_intent_secret': pi.client_secret,
                        'STRIPE_PUBLISHABLE_KEY': settings.STRIPE_API_PUBLIC_KEY,
                        'showSCA': True,
                        'success': {
                            'status': True,
                            'redirect': (
                                reverse('hosting:invoices')
                                if request.user.is_authenticated()
                                else reverse('datacenterlight:index')
                            ),
                            'msg_title': str(_('Thank you for the order.')),
                            'msg_body': str(
                                _('Your product will be provisioned as soon as'
                                  ' we receive a payment confirmation from '
                                  'Stripe. We will send you a confirmation '
                                  'email. You can always contact us at '
                                  'support@datacenterlight.ch')
                            )
                        },
                        'error': {
                            'status': False,
                            'redirect': "{url}#{section}".format(
                                url=(reverse(
                                    'show_product',
                                    kwargs={'product_slug':
                                                request.session[
                                                    'generic_payment_details']
                                                ['product_slug']}
                                ) if 'generic_payment_details' in request.session else
                                     reverse('datacenterlight:payment')
                                     ),
                                section='payment_error'
                            ),
                            'msg_title': str(_('Error.')),
                            'msg_body': str(
                                _('There was a payment related error.'
                                  ' On close of this popup, you will be redirected back to'
                                  ' the payment page.')
                            )
                        }
                    }
                    #clear_all_session_vars(request)
                    return JsonResponse(context)
                else:
                    logger.debug(
                        "Handle this case when "
                        "stripe.subscription_status is incomplete but "
                        "pi.status is neither requires_attention nor "
                        "requires_source_action")
                    msg = subscription_result.get('error')
                    return show_error(msg, self.request)
        provisioning_response = do_provisioning(
            req, user, stripe_api_cus_id,
            card_details_response, stripe_subscription_obj,
            stripe_onetime_charge, gp_details, specs, vm_template_id,
            template, request.session.get('billing_address_data'),
            self.request
        )

        if (provisioning_response and
                type(provisioning_response['response']) == JsonResponse):
            new_user = provisioning_response.get('user', None)
            if new_user:
                login(self.request, new_user)
            return provisioning_response['response']

        response = {
            'status': True,
            'redirect': (
                reverse('hosting:virtual_machines')
                if request.user.is_authenticated()
                else reverse('datacenterlight:index')
            ),
            'msg_title': str(_('Thank you for the order.')),
            'msg_body': str(
                _('Your VM will be up and running in a few moments.'
                  ' We will send you a confirmation email as soon as'
                  ' it is ready.'))
        }

        return JsonResponse(response)


def create_incomplete_intent_request(request):
    """
    Persist session variables so that they could be pick up
    in the webhook for processing.
    :param request:
    :return:
    """
    req = {
        'scheme': request.scheme,
        'host': request.get_host(),
        'language': get_language(),
        'new_user_hosting_key_id': request.session.get(
            'new_user_hosting_key_id', None),
        'card_id': request.session.get('card_id', None),
        'generic_payment_type': request.session.get(
            'generic_payment_type', None),
        'generic_payment_details': request.session.get(
            'generic_payment_details', None),
        'user': request.session.get('user', None)
    }
    return json.dumps(req)


def get_or_create_custom_user(request, stripe_api_cus_id):
    new_user = None
    name = request.get('user').get('name')
    email = request.get('user').get('email')

    try:
        custom_user = CustomUser.objects.get(email=email)
        stripe_customer = StripeCustomer.objects.filter(
            user_id=custom_user.id).first()
        if stripe_customer is None:
            stripe_customer = StripeCustomer.objects.create(
                user=custom_user, stripe_id=stripe_api_cus_id
            )
        stripe_customer_id = stripe_customer.id
    except CustomUser.DoesNotExist:
        logger.debug(
            "Customer {} does not exist.".format(email))
        password = CustomUser.get_random_password()
        base_url = "{0}://{1}".format(request['scheme'],
                                      request['host'])
        custom_user = CustomUser.register(
            name, password,
            email,
            app='dcl', base_url=base_url, send_email=True,
            account_details=password
        )
        logger.debug("Created user {}.".format(email))
        stripe_customer = StripeCustomer.objects. \
            create(user=custom_user, stripe_id=stripe_api_cus_id)
        stripe_customer_id = stripe_customer.id
        new_user = authenticate(username=custom_user.email,
                                password=password)
        logger.debug("User %s is authenticated" % custom_user.email)
        new_user_hosting_key_id = request.get('new_user_hosting_key_id', None)
        if new_user_hosting_key_id:
            user_hosting_key = UserHostingKey.objects.get(
                id=new_user_hosting_key_id)
            user_hosting_key.user = new_user
            user_hosting_key.save()
            logger.debug("User %s key is saved" % custom_user.email)
    return custom_user, new_user


def set_user_card(card_id, stripe_api_cus_id, custom_user,
                  card_details_response):
    if card_id:
        logger.debug("card_id %s was in request" % card_id)
        user_card_detail = UserCardDetail.objects.get(id=card_id)
        card_details_dict = {
            'last4': user_card_detail.last4,
            'brand': user_card_detail.brand,
            'card_id': user_card_detail.card_id
        }
        #if not user_card_detail.preferred:
        UserCardDetail.set_default_card(
            stripe_api_cus_id=stripe_api_cus_id,
            stripe_source_id=user_card_detail.card_id
        )
    else:
        logger.debug("card_id was NOT in request, using "
                     "card_details_response")
        ucd = UserCardDetail.get_or_create_user_card_detail(
            stripe_customer=custom_user.stripecustomer,
            card_details=card_details_response
        )
        UserCardDetail.save_default_card_local(
            custom_user.stripecustomer.stripe_id,
            ucd.card_id
        )
        card_details_dict = {
            'last4': ucd.last4,
            'brand': ucd.brand,
            'card_id': ucd.card_id
        }
    return card_details_dict


def do_provisioning_generic(
        request, stripe_api_cus_id, card_details_response,
        stripe_subscription_id, stripe_charge_id, gp_details,
        billing_address_data):
    user = request.get('user', None)
    logger.debug("generic_payment_type case")
    custom_user, new_user = get_or_create_custom_user(
        request, stripe_api_cus_id)
    logger.debug("%s %s" % (custom_user.email, custom_user.id))

    card_id = request.get('card_id', None)

    card_details_dict = set_user_card(card_id, stripe_api_cus_id, custom_user,
                                      card_details_response)

    logger.debug("After card details dict %s" % str(card_details_dict))

    # Save billing address
    billing_address_data.update({
        'user': custom_user.id
    })
    logger.debug('billing_address_data is {}'.format(billing_address_data))

    stripe_cus = StripeCustomer.objects.filter(
        stripe_id=stripe_api_cus_id
    ).first()
    billing_address = BillingAddress(
        cardholder_name=billing_address_data['cardholder_name'],
        street_address=billing_address_data['street_address'],
        city=billing_address_data['city'],
        postal_code=billing_address_data['postal_code'],
        country=billing_address_data['country'],
        vat_number=billing_address_data['vat_number']
    )
    billing_address.save()

    order = HostingOrder.create(
        price=request['generic_payment_details']['amount'],
        customer=stripe_cus,
        billing_address=billing_address,
        vm_pricing=VMPricing.get_default_pricing()
    )

    # Create a Hosting Bill
    HostingBill.create(customer=stripe_cus,
                       billing_address=billing_address)

    # Create Billing Address for User if he does not have one
    if not stripe_cus.user.billing_addresses.count():
        billing_address_data.update({
            'user': stripe_cus.user.id
        })
        billing_address_user_form = UserBillingAddressForm(
            billing_address_data
        )
        billing_address_user_form.is_valid()
        billing_address_user_form.save()

    recurring = request['generic_payment_details'].get('recurring')
    if recurring:
        logger.debug("recurring case")
        # Associate the given stripe subscription with the order
        order.set_subscription_id(
            stripe_subscription_id, card_details_dict
        )
        logger.debug("recurring case, set order subscription id done")
    else:
        logger.debug("one time charge case")
        # Associate the given stripe charge id with the order
        stripe_onetime_charge = stripe.Charge.retrieve(stripe_charge_id)
        order.set_stripe_charge(stripe_onetime_charge)

    # Set order status approved
    order.set_approved()
    order.generic_payment_description = gp_details["description"]
    order.generic_product_id = gp_details["product_id"]
    order.save()
    logger.debug("Order saved")
    # send emails
    context = {
        'name': user.get('name'),
        'email': user.get('email'),
        'amount': gp_details['amount'],
        'description': gp_details['description'],
        'recurring': gp_details['recurring'],
        'product_name': gp_details['product_name'],
        'product_id': gp_details['product_id'],
        'order_id': order.id
    }

    email_data = {
        'subject': (settings.DCL_TEXT +
                    " Payment received from %s" % context['email']),
        'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
        'to': ['info@ungleich.ch'],
        'body': "\n".join(
            ["%s=%s" % (k, v) for (k, v) in context.items()]),
        'reply_to': [context['email']],
    }
    send_plain_email_task.delay(email_data)
    recurring_text = _(" This is a monthly recurring plan.")
    if gp_details['recurring_interval'] == "year":
        recurring_text = _(" This is an yearly recurring plan.")

    email_data = {
        'subject': _("Confirmation of your payment"),
        'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
        'to': [user.get('email')],
        'body': _("Hi {name},\n\n"
                  "thank you for your order!\n"
                  "We have just received a payment of CHF {amount:.2f}"
                  " from you.{recurring}\n\n"
                  "Cheers,\nYour Data Center Light team".format(
            name=user.get('name'),
            amount=gp_details['amount'],
            recurring=(
                recurring_text
                if gp_details['recurring'] else ''
            )
        )
        ),
        'reply_to': ['info@ungleich.ch'],
    }
    send_plain_email_task.delay(email_data)
    redirect_url = reverse('datacenterlight:index')
    logger.debug("Sent user/admin emails")
    logger.debug("redirect_url = %s " % redirect_url)
    response = {
        'status': True,
        'redirect': redirect_url,
        'msg_title': str(_('Thank you for the payment.')),
        'msg_body': str(
            _('You will soon receive a confirmation email of the '
              'payment. You can always contact us at '
              'info@ungleich.ch for any question that you may have.')
        )
    }
    logger.debug("after response")
    logger.debug(str(response))
    return HttpResponse(status=200)


def do_provisioning(request, stripe_api_cus_id, card_details_response,
                    stripe_subscription_obj, stripe_onetime_charge, gp_details,
                    specs, vm_template_id, template, billing_address_data,
                    real_request):
    """
    :param request: a dict
        {
            'scheme': 'https',
            'host': 'domain',
            'language': 'en-us',
            'new_user_hosting_key_id': 1,
            'card_id': 1,   # if usercarddetail exists already,
            'generic_payment_type': 'generic'   # represents a generic payment
            'generic_payment_details': {
                'amount': 100,
                'recurring':
            },
            'user': {
                'name': 'John Doe',
                'email': 'john@doe.com'
            }
        }
    :param stripe_api_cus_id: 'cus_xxxxxxx' the actual stripe customer id str
    :param card_details_response:
    :param stripe_subscription_obj: The actual Stripe's Subscription Object
    :param stripe_onetime_charge: Stripe's Charge object
    :param gp_details:
    :param specs:
    :param vm_template_id:
    :param template:
    :param real_request:
    :return:
    """
    # Create user if the user is not logged in and if he is not already
    # registered
    custom_user, new_user = get_or_create_custom_user(
        request, stripe_api_cus_id)

    card_id = request.get('card_id', None)

    card_details_dict = set_user_card(card_id, stripe_api_cus_id, custom_user,
                  card_details_response)

    # Save billing address
    billing_address_data.update({
        'user': custom_user.id
    })
    logger.debug('billing_address_data is {}'.format(billing_address_data))

    generic_payment_type = request.get('generic_payment_type', None)
    if generic_payment_type:
        logger.debug("generic_payment_type case")
        stripe_cus = StripeCustomer.objects.filter(
            stripe_id=stripe_api_cus_id
        ).first()
        billing_address = BillingAddress(
            cardholder_name=billing_address_data['cardholder_name'],
            street_address=billing_address_data['street_address'],
            city=billing_address_data['city'],
            postal_code=billing_address_data['postal_code'],
            country=billing_address_data['country'],
            vat_number=billing_address_data['vat_number']
        )
        billing_address.save()

        order = HostingOrder.create(
            price=request['generic_payment_details']['amount'],
            customer=stripe_cus,
            billing_address=billing_address,
            vm_pricing=VMPricing.get_default_pricing()
        )

        # Create a Hosting Bill
        HostingBill.create(customer=stripe_cus,
                           billing_address=billing_address)

        # Create Billing Address for User if he does not have one
        if not stripe_cus.user.billing_addresses.count():
            billing_address_data.update({
                'user': stripe_cus.user.id
            })
            billing_address_user_form = UserBillingAddressForm(
                billing_address_data
            )
            billing_address_user_form.is_valid()
            billing_address_user_form.save()

        recurring = request['generic_payment_details'].get('recurring')
        if recurring:
            logger.debug("recurring case")
            # Associate the given stripe subscription with the order
            order.set_subscription_id(
                stripe_subscription_obj.id, card_details_dict
            )
            logger.debug("recurring case, set order subscription id done")
        else:
            logger.debug("one time charge case")
            # Associate the given stripe charge id with the order
            order.set_stripe_charge(stripe_onetime_charge)

        # Set order status approved
        order.set_approved()
        order.generic_payment_description = gp_details["description"]
        order.generic_product_id = gp_details["product_id"]
        order.save()
        logger.debug("Order saved")
        # send emails
        context = {
            'name': user.get('name'),
            'email': user.get('email'),
            'amount': gp_details['amount'],
            'description': gp_details['description'],
            'recurring': gp_details['recurring'],
            'product_name': gp_details['product_name'],
            'product_id': gp_details['product_id'],
            'order_id': order.id
        }

        email_data = {
            'subject': (settings.DCL_TEXT +
                        " Payment received from %s" % context['email']),
            'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
            'to': ['info@ungleich.ch'],
            'body': "\n".join(
                ["%s=%s" % (k, v) for (k, v) in context.items()]),
            'reply_to': [context['email']],
        }
        send_plain_email_task.delay(email_data)
        recurring_text = _(" This is a monthly recurring plan.")
        if gp_details['recurring_interval'] == "year":
            recurring_text = _(" This is an yearly recurring plan.")

        email_data = {
            'subject': _("Confirmation of your payment"),
            'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
            'to': [user.get('email')],
            'body': _("Hi {name},\n\n"
                      "thank you for your order!\n"
                      "We have just received a payment of CHF {amount:.2f}"
                      " from you.{recurring}\n\n"
                      "Cheers,\nYour Data Center Light team".format(
                            name=user.get('name'),
                            amount=gp_details['amount'],
                            recurring=(
                                recurring_text
                                if gp_details['recurring'] else ''
                            )
                        )
                    ),
            'reply_to': ['info@ungleich.ch'],
        }
        send_plain_email_task.delay(email_data)
        redirect_url = reverse('datacenterlight:index')
        logger.debug("Sent user/admin emails")
        if real_request:
            clear_all_session_vars(real_request)
            if real_request.user.is_authenticated():
                redirect_url = reverse('hosting:invoices')
        logger.debug("redirect_url = %s " % redirect_url)
        response = {
            'status': True,
            'redirect': redirect_url,
            'msg_title': str(_('Thank you for the payment.')),
            'msg_body': str(
                _('You will soon receive a confirmation email of the '
                  'payment. You can always contact us at '
                  'info@ungleich.ch for any question that you may have.')
            )
        }
        logger.debug("after response")
        logger.debug(str(response))
        return {'response': JsonResponse(response), 'user': new_user}

    user = {
        'name': custom_user.name,
        'email': custom_user.email,
        'username': custom_user.username,
        'pass': custom_user.password,
        'request_scheme': request['scheme'],
        'request_host': request['host'],
        'language': request['language'],
    }

    create_vm(
        billing_address_data, stripe_customer_id, specs,
        stripe_subscription_obj, card_details_dict, request,
        vm_template_id, template, user
    )

    if real_request:
        clear_all_session_vars(real_request)


def get_error_response_dict(msg, request):
    response = {
        'status': False,
        'redirect': "{url}#{section}".format(
            url=(reverse(
                'show_product',
                kwargs={'product_slug':
                            request.session['generic_payment_details']
                            ['product_slug']}
            ) if 'generic_payment_details' in request.session else
                 reverse('datacenterlight:payment')
                 ),
            section='payment_error'
        ),
        'msg_title': str(_('Error.')),
        'msg_body': str(
            _('There was a payment related error.'
              ' On close of this popup, you will be redirected back to'
              ' the payment page.'))
    }
    return response


def show_error(msg, request):
    messages.add_message(request, messages.ERROR, msg,
                         extra_tags='failed_payment')
    return JsonResponse(get_error_response_dict(msg,request))
