import json
import logging
import os
import pytz

from Crypto.PublicKey import RSA
from dateutil.relativedelta import relativedelta
from datetime import datetime
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from datacenterlight.models import VMPricing, VMTemplate, StripePlan
from membership.models import StripeCustomer, CustomUser
from utils.mixins import AssignPermissionsMixin
from utils.models import BillingAddress
from utils.stripe_utils import StripeUtils

logger = logging.getLogger(__name__)


class HostingPlan(models.Model):
    disk_size = models.FloatField(default=0.0)
    cpu_cores = models.FloatField(default=0.0)
    memory = models.FloatField(default=0.0)

    def serialize(self):
        return {
            'id': self.id,
            'cpu': self.cpu_cores,
            'memory': self.memory,
            'disk_size': self.disk_size,
            'price': self.price(),
        }

    @classmethod
    def get_serialized_configs(cls):
        return [cfg.serialize()
                for cfg in cls.objects.all()]

    def price(self):
        price = self.disk_size * 0.6
        price += self.cpu_cores * 5
        price += self.memory * 2
        return price


class OrderDetail(AssignPermissionsMixin, models.Model):
    vm_template = models.ForeignKey(
        VMTemplate, blank=True, null=True, default=None,
        on_delete=models.SET_NULL
    )
    cores = models.IntegerField(default=0)
    memory = models.IntegerField(default=0)
    hdd_size = models.IntegerField(default=0)
    ssd_size = models.IntegerField(default=0)

    def __str__(self):
        return "Not available" if self.vm_template is None else (
            "%s - %s, %s cores, %s GB RAM, %s GB SSD" % (
                self.vm_template.name, self.vm_template.vm_type, self.cores,
                self.memory, self.ssd_size
            )
        )


class GenericProduct(AssignPermissionsMixin, models.Model):
    permissions = ('view_genericproduct',)
    product_name = models.CharField(max_length=128, default="")
    product_slug = models.SlugField(
        unique=True,
        help_text=(
            'An mandatory unique slug for the product'
        )
    )
    product_description = models.CharField(max_length=500, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    product_price = models.DecimalField(max_digits=6, decimal_places=2)
    product_vat = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    product_is_subscription = models.BooleanField(default=True)

    def __str__(self):
        return self.product_name

    def get_actual_price(self):
        return round(
            self.product_price + (self.product_price * self.product_vat), 2
        )


class HostingOrder(AssignPermissionsMixin, models.Model):
    ORDER_APPROVED_STATUS = 'Approved'
    ORDER_DECLINED_STATUS = 'Declined'

    vm_id = models.IntegerField(default=0)
    customer = models.ForeignKey(StripeCustomer)
    billing_address = models.ForeignKey(BillingAddress)
    created_at = models.DateTimeField(auto_now_add=True)
    approved = models.BooleanField(default=False)
    last4 = models.CharField(max_length=4)
    cc_brand = models.CharField(max_length=128)
    stripe_charge_id = models.CharField(max_length=100, null=True)
    price = models.FloatField()
    subscription_id = models.CharField(max_length=100, null=True)
    vm_pricing = models.ForeignKey(VMPricing)
    order_detail = models.ForeignKey(
        OrderDetail, null=True, blank=True, default=None,
        on_delete=models.SET_NULL
    )
    generic_product = models.ForeignKey(
        GenericProduct, null=True, blank=True, default=None,
        on_delete=models.SET_NULL
    )
    generic_payment_description = models.CharField(
        max_length=500, null=True
    )
    permissions = ('view_hostingorder',)

    class Meta:
        permissions = (
            ('view_hostingorder', 'View Hosting Order'),
        )

    def __str__(self):
        hosting_order_str = ("Order Nr: #{} - VM_ID: {} - {} - {} - "
                             "Specs: {} - Price: {}").format(
            self.id, self.vm_id, self.customer.user.email, self.created_at,
            self.order_detail, self.price
        )
        if self.generic_product_id is not None:
            hosting_order_str += " - Generic Payment"
            if self.stripe_charge_id is not None:
                hosting_order_str += " - One time charge"
            else:
                hosting_order_str += " - Recurring"
        return hosting_order_str

    @cached_property
    def status(self):
        return self.ORDER_APPROVED_STATUS if self.approved else self.ORDER_DECLINED_STATUS

    @classmethod
    def create(cls, price=None, vm_id=0, customer=None,
               billing_address=None, vm_pricing=None):
        instance = cls.objects.create(
            price=price,
            vm_id=vm_id,
            customer=customer,
            billing_address=billing_address,
            vm_pricing=vm_pricing
        )
        instance.assign_permissions(customer.user)
        return instance

    def set_approved(self):
        self.approved = True
        self.save()

    def set_stripe_charge(self, stripe_charge):
        self.stripe_charge_id = stripe_charge.id
        self.last4 = stripe_charge.source.last4
        self.cc_brand = stripe_charge.source.brand
        self.save()

    def set_subscription_id(self, subscription_id, cc_details):
        """
        When creating a Stripe subscription, we have subscription id.
        We store this in the subscription_id field.
        This method sets the subscription id
        and the last4 and credit card brands used for this order.

        :param subscription_id: Stripe's subscription id
        :param cc_details: A dict containing card details
        {last4, brand}
        :return:
        """
        self.subscription_id = subscription_id
        self.last4 = cc_details.get('last4')
        self.cc_brand = cc_details.get('brand')
        self.save()

    def get_cc_data(self):
        return {
            'last4': self.last4,
            'cc_brand': self.cc_brand,
        } if self.last4 and self.cc_brand else None


class UserHostingKey(models.Model):
    user = models.ForeignKey(CustomUser)
    public_key = models.TextField()
    private_key = models.FileField(upload_to='private_keys', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=100)

    @staticmethod
    def generate_RSA(bits=2048):
        '''
        Generate an RSA keypair with an exponent of 65537 in PEM format
        param: bits The key length in bits
        Return private key and public key
        '''
        new_key = RSA.generate(2048, os.urandom)
        public_key = new_key.publickey().exportKey("OpenSSH")
        private_key = new_key.exportKey("PEM")
        return private_key, public_key

    @classmethod
    def generate_keys(cls):
        private_key, public_key = cls.generate_RSA()
        # self.public_key = public_key
        # self.save(update_fields=['public_key'])
        return private_key, public_key


class HostingBill(AssignPermissionsMixin, models.Model):
    customer = models.ForeignKey(StripeCustomer)
    billing_address = models.ForeignKey(BillingAddress)
    total_price = models.FloatField(default=0.0)

    permissions = ('view_hostingbill',)

    class Meta:
        permissions = (
            ('view_hostingbill', 'View Hosting Bill'),
        )

    def __str__(self):
        return "%s" % (self.customer.user.email)

    @classmethod
    def create(cls, customer=None, billing_address=None):
        instance = cls.objects.create(customer=customer,
                                      billing_address=billing_address)
        return instance


class MonthlyHostingBill(AssignPermissionsMixin, models.Model):
    """
    Corresponds to Invoice object of Stripe
    """
    customer = models.ForeignKey(StripeCustomer)
    order = models.ForeignKey(HostingOrder)
    created = models.DateTimeField(help_text="When the invoice was created")
    receipt_number = models.CharField(
        help_text="The receipt number that is generated on Stripe",
        max_length=100
    )
    invoice_number = models.CharField(
        help_text="The invoice number that is generated on Stripe",
        max_length=100
    )
    paid_at = models.DateTimeField(help_text="Date on which the bill was paid")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    billing_reason = models.CharField(max_length=25)
    discount = models.PositiveIntegerField()
    total = models.IntegerField()
    lines_data_count = models.IntegerField()
    invoice_id = models.CharField(unique=True, max_length=100)
    lines_meta_data_csv = models.TextField(default="")
    subscription_ids_csv = models.TextField(default="")

    permissions = ('view_monthlyhostingbill',)

    class Meta:
        permissions = (
            ('view_monthlyhostingbill', 'View Monthly Hosting'),
        )

    @classmethod
    def create(cls, args):
        # Try to infer the HostingOrder from subscription id or VM_ID
        if len(args['subscription_ids_csv']) > 0:
            sub_ids = [sub_id.strip() for sub_id in args['subscription_ids_csv'].split(",")]
            set_sub_ids = set(sub_ids)
            if len(set_sub_ids) == 1:
                # the multiple line items belong to the same subscription
                sub_id = set_sub_ids.pop()
                try:
                    args['order'] = HostingOrder.objects.get(
                        subscription_id=sub_id
                    )
                except HostingOrder.DoesNotExist as dne:
                    logger.error("Hosting order for {} doesn't exist".format(
                        sub_id
                    ))
                    args['order'] = None
            else:
                logger.debug(
                    "More than one subscriptions"
                    "for MonthlyHostingBill {}".format(args['invoice_id'])
                )
                logger.debug("SUB_IDS={}".format(','.join(sub_ids)))
                logger.debug("Not importing invoices")
                return None
        elif len(args['lines_meta_data_csv']) > 0:
            vm_ids = [vm_id.strip() for vm_id in args['lines_meta_data_csv'].split(",")]
            if len(vm_ids) == 1:
                args['order'] = HostingOrder.objects.get(vm_id=vm_ids[0])
            else:
                logger.debug(
                    "More than one VM_ID"
                    "for MonthlyHostingBill {}".format(args['invoice_id'])
                )
                logger.debug("VM_IDS={}".format(','.join(vm_ids)))
                logger.debug("Not importing invoices")
                return None
        else:
            logger.debug("Neither subscription id nor vm_id available")
            logger.debug("Can't import invoice")
            return None

        instance = cls.objects.create(
            created=datetime.utcfromtimestamp(
                args['created']).replace(tzinfo=pytz.utc),
            receipt_number=(
                args['receipt_number']
                if args['receipt_number'] is not None else ''
            ),
            invoice_number=(
                args['invoice_number']
                if args['invoice_number'] is not None else ''
            ),
            paid_at=datetime.utcfromtimestamp(
                args['paid_at']).replace(tzinfo=pytz.utc),
            period_start=datetime.utcfromtimestamp(
                args['period_start']).replace(tzinfo=pytz.utc),
            period_end=datetime.utcfromtimestamp(
                args['period_end']).replace(tzinfo=pytz.utc),
            billing_reason=args['billing_reason'],
            discount=args['discount'],
            total=args['total'],
            lines_data_count=args['lines_data_count'],
            invoice_id=args['invoice_id'],
            lines_meta_data_csv=args['lines_meta_data_csv'],
            customer=args['customer'],
            order=args['order'],
            subscription_ids_csv=args['subscription_ids_csv'],
        )

        if 'line_items' in args:
            line_items = args['line_items']
            for item in line_items:
                stripe_plan = None
                if item.type == "subscription" or item.type == "invoiceitem":
                    # Check stripe plan and prepare it for linking to bill item
                    stripe_plan_id = item.plan.id
                    try:
                        stripe_plan = StripePlan.objects.get(
                            stripe_plan_id=stripe_plan_id
                        )
                    except StripePlan.DoesNotExist as dne:
                        logger.error(
                            "StripePlan %s doesn't exist" % stripe_plan_id
                        )
                        if stripe_plan_id is not None:
                            # Create Stripe Plan because we don't have it
                            stripe_plan = StripePlan.objects.create(
                                stripe_plan_id=stripe_plan_id,
                                stripe_plan_name=item.plan.name,
                                amount=item.plan.amount,
                                interval=item.plan.interval
                            )
                            logger.debug("Creatd StripePlan " + stripe_plan_id)
                line_item_instance = HostingBillLineItem.objects.create(
                    monthly_hosting_bill=instance,
                    amount=item.amount,
                    # description seems to be set to null in the Stripe
                    # response for an invoice
                    description="" if item.description is None else item.description,
                    discountable=item.discountable,
                    metadata=json.dumps(item.metadata),
                    period_start=datetime.utcfromtimestamp(item.period.start).replace(tzinfo=pytz.utc),                                            period_end=datetime.utcfromtimestamp(item.period.end).replace(tzinfo=pytz.utc),
                    proration=item.proration,
                    quantity=item.quantity,
                    # Strange that line item does not have unit_amount but api
                    # states that it is present
                    # https://stripe.com/docs/api/invoiceitems/object#invoiceitem_object-unit_amount
                    # So, for the time being I set the unit_amount to 0 if not
                    # found in the line item
                    unit_amount=item.unit_amount if hasattr(item, "unit_amount") else 0,
                    stripe_plan=stripe_plan
                )
                line_item_instance.assign_permissions(instance.customer.user)
        instance.assign_permissions(instance.customer.user)
        return instance

    def total_in_chf(self):
        """
        Returns amount in chf. The total amount in this model is in cents.
        Hence we multiply it by 0.01 to obtain the result

        :return:
        """
        return self.total * 0.01

    def discount_in_chf(self):
        """
        Returns discount in chf.

        :return:
        """
        return self.discount * 0.01

    def get_vm_id(self):
        """
        Returns the VM_ID metadata if set in this MHB else returns None
        :return:
        """
        return_value = None
        if len(self.lines_meta_data_csv) > 0:
            vm_ids = [vm_id.strip() for vm_id in
                      self.lines_meta_data_csv.split(",")]
            unique_vm_ids=set(vm_ids)
            unique_vm_ids.discard("")
            if len(unique_vm_ids) == 1:
                vm_id = unique_vm_ids.pop()
                logger.debug("Getting invoice for {}".format(vm_id))
                return vm_id
            else:
                logger.debug(
                    "More than one VM_ID"
                    "for MonthlyHostingBill {}".format(self.invoice_id)
                )
                logger.debug("VM_IDS={}".format(unique_vm_ids))
        return return_value

    def get_period_start(self):
        """
        Return the period start of the invoice for the line items
        :return:
        """
        items = HostingBillLineItem.objects.filter(monthly_hosting_bill=self)
        if len(items) > 0:
            return items[0].period_start
        else:
            return self.period_start

    def get_period_end(self):
        """
        Return the period end of the invoice for the line items
        :return:
        """
        items = HostingBillLineItem.objects.filter(monthly_hosting_bill=self)
        if len(items) > 0:
            return items[0].period_end
        else:
            return self.period_end


class HostingBillLineItem(AssignPermissionsMixin, models.Model):
    """
    Corresponds to InvoiceItem object of Stripe
    """
    monthly_hosting_bill = models.ForeignKey(MonthlyHostingBill,
                                             on_delete=models.CASCADE)
    stripe_plan = models.ForeignKey(StripePlan, null=True,
                                    on_delete=models.CASCADE)
    amount = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=255)
    discountable = models.BooleanField()
    metadata = models.CharField(max_length=128)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    proration = models.BooleanField()
    quantity = models.PositiveIntegerField()
    unit_amount = models.PositiveIntegerField()
    permissions = ('view_hostingbilllineitem',)

    class Meta:
        permissions = (
            ('view_hostingbilllineitem', 'View Monthly Hosting Bill Line Item'),
        )

    def amount_in_chf(self):
        """
        Returns amount in chf. The amount in this model is in cents (as in
        Stripe). Hence we multiply it by 0.01 to obtain the result

        :return:
        """
        return self.amount * 0.01

    def unit_amount_in_chf(self):
        """
        Returns unit amount in chf. If its 0, we obtain it from amount and
        quantity.

        :return:
        """
        if self.unit_amount == 0:
            return round((self.amount / self.quantity) * 0.01, 2)
        else:
            return self.unit_amount * 0.01

    def get_item_detail_str(self):
        """
        Returns line item html string representation
        :return:
        """
        item_detail = ""
        if self.metadata is not None and len(self.metadata) > 0:
            try:
                vm_dict = json.loads(self.metadata)
                item_detail = "VM ID: {}<br/>".format(vm_dict["VM_ID"])
            except ValueError as ve:
                logger.error(
                    "Could not parse VM in metadata {}. Detail {}".format(
                        self.metadata, str(ve)
                    )
                )
            vm_conf = StripeUtils.get_vm_config_from_stripe_id(
                self.stripe_plan.stripe_plan_id
            )
            if vm_conf is not None:
                item_detail += ("<b>Cores</b>: {}<br/><b>RAM</b>: {} GB<br/>"
                                "<b>SSD</b>: {} GB<br/>").format(
                    vm_conf['cores'], int(float(vm_conf['ram'])),
                    vm_conf['ssd']
                )
        return item_detail

class VMDetail(models.Model):
    user = models.ForeignKey(CustomUser)
    vm_id = models.IntegerField(default=0)
    disk_size = models.FloatField(default=0.0)
    cores = models.FloatField(default=0.0)
    memory = models.FloatField(default=0.0)
    configuration = models.CharField(default='', max_length=25)
    ipv4 = models.TextField(default='')
    ipv6 = models.TextField(default='')
    created_at = models.DateTimeField(auto_now_add=True)
    terminated_at = models.DateTimeField(null=True)

    def end_date(self):
        end_date = self.terminated_at if self.terminated_at else timezone.now()
        months = relativedelta(end_date, self.created_at).months or 1
        end_date = self.created_at + relativedelta(months=months, days=-1)
        return end_date


class UserCardDetail(AssignPermissionsMixin, models.Model):
    permissions = ('view_usercarddetail',)
    stripe_customer = models.ForeignKey(StripeCustomer)
    last4 = models.CharField(max_length=4)
    brand = models.CharField(max_length=128)
    card_id = models.CharField(max_length=100, blank=True, default='')
    fingerprint = models.CharField(max_length=100)
    exp_month = models.IntegerField(null=False)
    exp_year = models.IntegerField(null=False)
    preferred = models.BooleanField(default=False)

    class Meta:
        permissions = (
            ('view_usercarddetail', 'View User Card'),
        )

    @classmethod
    def create(cls, stripe_customer=None, last4=None, brand=None,
               fingerprint=None, exp_month=None, exp_year=None, card_id=None,
               preferred=False):
        instance = cls.objects.create(
            stripe_customer=stripe_customer, last4=last4, brand=brand,
            fingerprint=fingerprint, exp_month=exp_month, exp_year=exp_year,
            card_id=card_id, preferred=preferred
        )
        instance.assign_permissions(stripe_customer.user)
        return instance

    @classmethod
    def get_all_cards_list(cls, stripe_customer):
        """
        Get all the cards of the given customer as a list

        :param stripe_customer: The StripeCustomer object
        :return: A list of all cards; an empty list if the customer object is
                 None
        """
        cards_list = []
        if stripe_customer is None:
            return cards_list
        user_card_details = UserCardDetail.objects.filter(
            stripe_customer_id=stripe_customer.id
        ).order_by('-preferred', 'id')
        for card in user_card_details:
            cards_list.append({
                'last4': card.last4, 'brand': card.brand, 'id': card.id,
                'preferred': card.preferred
            })
        return cards_list

    @classmethod
    def get_or_create_user_card_detail(cls, stripe_customer, card_details):
        """
        A method that checks if a UserCardDetail object exists already
        based upon the given card_details and creates it for the given
        customer if it does not exist. It returns the UserCardDetail object
        matching the given card_details if it exists.

        :param stripe_customer: The given StripeCustomer object to whom the
                card object should belong to
        :param card_details: A dictionary identifying a given card
        :return: UserCardDetail object
        """
        try:
            if ('fingerprint' in card_details and 'exp_month' in card_details
                    and 'exp_year' in card_details):
                card_detail = UserCardDetail.objects.get(
                    stripe_customer=stripe_customer,
                    fingerprint=card_details['fingerprint'],
                    exp_month=card_details['exp_month'],
                    exp_year=card_details['exp_year']
                )
            else:
                raise UserCardDetail.DoesNotExist()
        except UserCardDetail.DoesNotExist:
            preferred = False
            if 'preferred' in card_details:
                preferred = card_details['preferred']
            card_detail = UserCardDetail.create(
                stripe_customer=stripe_customer,
                last4=card_details['last4'],
                brand=card_details['brand'],
                fingerprint=card_details['fingerprint'],
                exp_month=card_details['exp_month'],
                exp_year=card_details['exp_year'],
                card_id=card_details['card_id'],
                preferred=preferred
            )
        return card_detail

    @staticmethod
    def set_default_card(stripe_api_cus_id, stripe_source_id):
        """
        Sets the given stripe source as the default source for the given
        Stripe customer
        :param stripe_api_cus_id: Stripe customer id
        :param stripe_source_id: The Stripe source id
        :return:
        """
        stripe_utils = StripeUtils()
        cus_response = stripe_utils.get_customer(stripe_api_cus_id)
        cu = cus_response['response_object']
        cu.default_source = stripe_source_id
        cu.save()
        UserCardDetail.save_default_card_local(
            stripe_api_cus_id, stripe_source_id
        )

    @staticmethod
    def set_default_card_from_stripe(stripe_api_cus_id):
        stripe_utils = StripeUtils()
        cus_response = stripe_utils.get_customer(stripe_api_cus_id)
        cu = cus_response['response_object']
        default_source = cu.default_source
        if default_source is not None:
            UserCardDetail.save_default_card_local(
                stripe_api_cus_id, default_source
            )

    @staticmethod
    def save_default_card_local(stripe_api_cus_id, card_id):
        stripe_cust = StripeCustomer.objects.get(stripe_id=stripe_api_cus_id)
        user_card_detail = UserCardDetail.objects.get(
            stripe_customer=stripe_cust, card_id=card_id
        )
        for card in stripe_cust.usercarddetail_set.all():
            card.preferred = False
            card.save()
        user_card_detail.preferred = True
        user_card_detail.save()

    @staticmethod
    def get_user_card_details(stripe_customer, card_details):
        """
        A utility function to check whether a StripeCustomer is already
        associated with the card having given details

        :param stripe_customer:
        :param card_details:
        :return: The UserCardDetails object if it exists, None otherwise
        """
        try:
            ucd = UserCardDetail.objects.get(
                stripe_customer=stripe_customer,
                fingerprint=card_details['fingerprint'],
                exp_month=card_details['exp_month'],
                exp_year=card_details['exp_year']
            )
            return ucd
        except UserCardDetail.DoesNotExist:
            return None
