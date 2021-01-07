import logging
import re

import stripe
from django.conf import settings

from datacenterlight.models import StripePlan

stripe.api_key = settings.STRIPE_API_PRIVATE_KEY
logger = logging.getLogger(__name__)


def handleStripeError(f):
    def handleProblems(*args, **kwargs):
        response = {
            'paid': False,
            'response_object': None,
            'error': None
        }

        common_message = "Currently it's not possible to make payments."
        try:
            response_object = f(*args, **kwargs)
            response = {
                'response_object': response_object,
                'error': None
            }
            return response
        except stripe.error.CardError as e:
            # Since it's a decline, stripe.error.CardError will be caught
            body = e.json_body
            err = body['error']
            response.update({'error': err['message']})
            logger.error(str(e))
            return response
        except stripe.error.RateLimitError as e:
            logger.error(str(e))
            response.update(
                {'error': "Too many requests made to the API too quickly"})
            return response
        except stripe.error.InvalidRequestError as e:
            logger.error(str(e))
            response.update({'error': str(e._message)})
            return response
        except stripe.error.AuthenticationError as e:
            # Authentication with Stripe's API failed
            # (maybe you changed API keys recently)
            logger.error(str(e))
            response.update({'error': str(e)})
            return response
        except stripe.error.APIConnectionError as e:
            logger.error(str(e))
            response.update({'error': str(e)})
            return response
        except stripe.error.StripeError as e:
            # maybe send email
            logger.error(str(e))
            response.update({'error': str(e)})
            return response
        except Exception as e:
            # maybe send email
            logger.error(str(e))
            response.update({'error': str(e)})
            return response

    return handleProblems


class StripeUtils(object):
    CURRENCY = 'chf'
    INTERVAL = 'month'
    SUCCEEDED_STATUS = 'succeeded'
    RESOURCE_ALREADY_EXISTS_ERROR_CODE = 'resource_already_exists'
    STRIPE_NO_SUCH_PLAN = 'No such plan'
    PLAN_EXISTS_ERROR_MSG = 'Plan {} exists already.\nCreating a local StripePlan now.'
    PLAN_DOES_NOT_EXIST_ERROR_MSG = 'Plan {} does not exist.'

    def __init__(self):
        self.stripe = stripe

    def update_customer_token(self, customer, token):
        customer.source = token
        customer.save()

    @handleStripeError
    def associate_customer_card(self, stripe_customer_id, id_payment_method,
                                set_as_default=False):
        customer = stripe.Customer.retrieve(stripe_customer_id)
        stripe.PaymentMethod.attach(
            id_payment_method,
            customer=stripe_customer_id,
        )
        if set_as_default:
            customer.invoice_settings.default_payment_method = id_payment_method
            customer.save()
        return True

    @handleStripeError
    def dissociate_customer_card(self, stripe_customer_id, card_id):
        customer = stripe.Customer.retrieve(stripe_customer_id)
        if card_id.startswith("pm"):
            logger.debug("PaymentMethod %s detached %s" % (card_id,
                                                           stripe_customer_id))
            pm = stripe.PaymentMethod.retrieve(card_id)
            stripe.PaymentMethod.detach(card_id)
            pm.delete()
        else:
            logger.debug("card %s detached %s" % (card_id, stripe_customer_id))
            card = customer.sources.retrieve(card_id)
            card.delete()

    @handleStripeError
    def update_customer_card(self, customer_id, token):
        customer = stripe.Customer.retrieve(customer_id)
        current_card_token = customer.default_source
        customer.sources.retrieve(current_card_token).delete()
        customer.source = token
        customer.save()
        credit_card_raw_data = customer.sources.data.pop()
        new_card_data = {
            'last4': credit_card_raw_data.last4,
            'brand': credit_card_raw_data.brand
        }
        return new_card_data

    @handleStripeError
    def get_card_details(self, customer_id):
        customer = stripe.Customer.retrieve(customer_id)
        credit_card_raw_data = customer.sources.data.pop()
        card_details = {
            'last4': credit_card_raw_data.last4,
            'brand': credit_card_raw_data.brand,
            'exp_month': credit_card_raw_data.exp_month,
            'exp_year': credit_card_raw_data.exp_year,
            'fingerprint': credit_card_raw_data.fingerprint,
            'card_id': credit_card_raw_data.id
        }
        return card_details

    @handleStripeError
    def get_all_invoices(self, customer_id, created_gt):
        return_list = []
        has_more_invoices = True
        starting_after = False
        while has_more_invoices:
            if starting_after:
                invoices = stripe.Invoice.list(
                    limit=10, customer=customer_id, created={'gt': created_gt},
                    starting_after=starting_after
                )
            else:
                invoices = stripe.Invoice.list(
                    limit=10, customer=customer_id, created={'gt': created_gt}
                )
            has_more_invoices = invoices.has_more
            for invoice in invoices.data:
                sub_ids = []
                for line in invoice.lines.data:
                    if line.type == 'subscription':
                        sub_ids.append(line.id)
                    elif line.type == 'invoiceitem':
                        sub_ids.append(line.subscription)
                    else:
                        sub_ids.append('')
                invoice_details = {
                    'created': invoice.created,
                    'receipt_number': invoice.receipt_number,
                    'invoice_number': invoice.number,
                    'paid_at': invoice.status_transitions.paid_at if invoice.paid else 0,
                    'period_start': invoice.period_start,
                    'period_end': invoice.period_end,
                    'billing_reason': invoice.billing_reason,
                    'discount': invoice.discount.coupon.amount_off if invoice.discount else 0,
                    'total': invoice.total,
                    # to see how many line items we have in this invoice and
                    # then later check if we have more than 1
                    'lines_data_count': len(invoice.lines.data) if invoice.lines.data is not None else 0,
                    'invoice_id': invoice.id,
                    'lines_meta_data_csv': ','.join(
                        [line.metadata.VM_ID if hasattr(line.metadata, 'VM_ID') else '' for line in invoice.lines.data]
                    ),
                    'subscription_ids_csv': ','.join(sub_ids),
                    'line_items': invoice.lines.data
                }
                starting_after = invoice.id
                return_list.append(invoice_details)
        return return_list

    @handleStripeError
    def get_cards_details_from_token(self, token):
        stripe_token = stripe.Token.retrieve(token)
        card_details = {
            'last4': stripe_token.card.last4,
            'brand': stripe_token.card.brand,
            'exp_month': stripe_token.card.exp_month,
            'exp_year': stripe_token.card.exp_year,
            'fingerprint': stripe_token.card.fingerprint,
            'card_id': stripe_token.card.id
        }
        return card_details

    @handleStripeError
    def get_cards_details_from_payment_method(self, payment_method_id):
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
        # payment_method does not always seem to have a card with id
        # if that is the case, fallback to payment_method_id for card_id
        card_id = payment_method_id
        if hasattr(payment_method.card, 'id'):
            card_id = payment_method.card.id
        card_details = {
            'last4': payment_method.card.last4,
            'brand': payment_method.card.brand,
            'exp_month': payment_method.card.exp_month,
            'exp_year': payment_method.card.exp_year,
            'fingerprint': payment_method.card.fingerprint,
            'card_id': card_id
        }
        return card_details

    def check_customer(self, stripe_cus_api_id, user, token):
        try:
            customer = stripe.Customer.retrieve(stripe_cus_api_id)
        except stripe.InvalidRequestError:
            customer = self.create_customer(token, user.email, user.name)
            user.stripecustomer.stripe_id = customer.get(
                'response_object').get('id')
            user.stripecustomer.save()
        if type(customer) is dict:
            customer = customer['response_object']
        return customer

    @handleStripeError
    def get_customer(self, stripe_api_cus_id):
        customer = stripe.Customer.retrieve(stripe_api_cus_id)
        # data = customer.get('response_object')
        return customer

    @handleStripeError
    def create_customer(self, id_payment_method, email, name=None):
        if name is None or name.strip() == "":
            name = email
        customer = self.stripe.Customer.create(
            payment_method=id_payment_method,
            description=name,
            email=email
        )
        return customer

    @handleStripeError
    def make_charge(self, amount=None, customer=None):
        _amount = float(amount)
        amount = int(_amount * 100)  # stripe amount unit, in cents
        charge = self.stripe.Charge.create(
            amount=amount,  # in cents
            currency=self.CURRENCY,
            customer=customer
        )
        return charge

    @handleStripeError
    def get_or_create_stripe_plan(self, amount, name, stripe_plan_id,
                                  interval=""):
        """
        This function checks if a StripePlan with the given
        stripe_plan_id already exists. If it exists then the function
        returns this object otherwise it creates a new StripePlan and
        returns the new object.

        :param amount: The amount in CHF
        :param name: The name of the Stripe plan to be created.
        :param stripe_plan_id: The id of the Stripe plan to be
               created. Use get_stripe_plan_id_string function to
               obtain the name of the plan to be created
        :param interval: str representing the interval of the Plan
               Specifies billing frequency. Either day, week, month or year.
               Ref: https://stripe.com/docs/api/plans/create#create_plan-interval
               The default is month
        :return: The StripePlan object if it exists else creates a
               Plan object in Stripe and a local StripePlan and
               returns it. Returns None in case of Stripe error
        """
        _amount = float(amount)
        amount = int(_amount * 100)  # stripe amount unit, in cents
        stripe_plan_db_obj = None
        plan_interval = interval if interval is not "" else self.INTERVAL
        try:
            stripe_plan_db_obj = StripePlan.objects.get(
                stripe_plan_id=stripe_plan_id)
        except StripePlan.DoesNotExist:
            try:
                self.stripe.Plan.create(
                    amount=amount,
                    interval=plan_interval,
                    name=name,
                    currency=self.CURRENCY,
                    id=stripe_plan_id)
                stripe_plan_db_obj = StripePlan.objects.create(
                    stripe_plan_id=stripe_plan_id)
            except stripe.error.InvalidRequestError as e:
                logger.error(str(e))
                logger.error("error_code = %s" % str(e.__dict__))
                if self.RESOURCE_ALREADY_EXISTS_ERROR_CODE in e.error.code:
                    logger.debug(
                        self.PLAN_EXISTS_ERROR_MSG.format(stripe_plan_id))
                    stripe_plan_db_obj, c = StripePlan.objects.get_or_create(
                        stripe_plan_id=stripe_plan_id)
                    if c:
                        logger.debug("Created stripe plan %s" % stripe_plan_id)
                    else:
                        logger.debug("Plan %s exists already" % stripe_plan_id)
        return stripe_plan_db_obj

    @handleStripeError
    def delete_stripe_plan(self, stripe_plan_id):
        """
        Deletes the Plan in Stripe and also deletes the local db copy
        of the plan if it exists

        :param stripe_plan_id: The stripe plan id that needs to be
               deleted
        :return: True if the plan was deleted successfully from
               Stripe, False otherwise.
        """
        return_value = False
        try:
            plan = self.stripe.Plan.retrieve(stripe_plan_id)
            plan.delete()
            return_value = True
            StripePlan.objects.filter(
                stripe_plan_id=stripe_plan_id).all().delete()
        except stripe.error.InvalidRequestError as e:
            if self.STRIPE_NO_SUCH_PLAN in str(e):
                logger.debug(
                    self.PLAN_DOES_NOT_EXIST_ERROR_MSG.format(stripe_plan_id))
        return return_value

    @handleStripeError
    def subscribe_customer_to_plan(self, customer, plans, trial_end=None,
                                   coupon="", tax_rates=list(),
                                   default_payment_method=""):
        """
        Subscribes the given customer to the list of given plans

        :param default_payment_method:
        :param tax_rates:
        :param coupon:
        :param customer: The stripe customer identifier
        :param plans: A list of stripe plans.
        :param trial_end: An integer representing when the Stripe subscription
               is supposed to end
        Ref: https://stripe.com/docs/api/python#create_subscription-items
              e.g.
                    plans = [
                                {
                                  "plan": "dcl-v1-cpu-2-ram-5gb-ssd-10gb",
                                },
                            ]
        :return: The subscription StripeObject
        """
        logger.debug("Subscribing %s to plan %s : coupon = %s" % (
            customer, str(plans), str(coupon)
        ))
        subscription_result = self.stripe.Subscription.create(
            customer=customer, items=plans, trial_end=trial_end,
            coupon=coupon,
            default_tax_rates=tax_rates,
            payment_behavior='allow_incomplete',
            default_payment_method=default_payment_method
        )
        logger.debug("Done subscribing")
        return subscription_result

    @handleStripeError
    def set_subscription_metadata(self, subscription_id, metadata):
        subscription = stripe.Subscription.retrieve(subscription_id)
        subscription.metadata = metadata
        subscription.save()

    @handleStripeError
    def unsubscribe_customer(self, subscription_id):
        """
        Cancels a given subscription

        :param subscription_id: The Stripe subscription id string
        :return:
        """
        sub = stripe.Subscription.retrieve(subscription_id)
        return sub.delete()

    @handleStripeError
    def make_payment(self, customer, amount, token):
        charge = self.stripe.Charge.create(
            amount=amount,  # in cents
            currency=self.CURRENCY,
            customer=customer
        )
        return charge

    @staticmethod
    def get_stripe_plan_id(cpu, ram, ssd, version, app='dcl', hdd=None,
                           price=None, excl_vat=True):
        """
        Returns the Stripe plan id string of the form
        `dcl-v1-cpu-2-ram-5gb-ssd-10gb` based on the input parameters

        :param cpu: The number of cores
        :param ram: The size of the RAM in GB
        :param ssd: The size of ssd storage in GB
        :param hdd: The size of hdd storage in GB
        :param version: The version of the Stripe plans
        :param app: The application to which the stripe plan belongs
        to. By default it is 'dcl'
        :param price: The price for this plan
        :return: A string of the form `dcl-v1-cpu-2-ram-5gb-ssd-10gb`
        """
        dcl_plan_string = 'cpu-{cpu}-ram-{ram}gb-ssd-{ssd}gb'.format(cpu=cpu,
                                                                     ram=ram,
                                                                     ssd=ssd)
        if hdd is not None:
            dcl_plan_string = '{dcl_plan_string}-hdd-{hdd}gb'.format(
                dcl_plan_string=dcl_plan_string, hdd=hdd)
        stripe_plan_id_string = '{app}-v{version}-{plan}'.format(
            app=app,
            version=version,
            plan=dcl_plan_string
        )
        if price is not None:
            stripe_plan_id_string = '{}-{}chf'.format(
                stripe_plan_id_string,
                round(price, 2)
            )
        if excl_vat:
            stripe_plan_id_string = '{}-{}'.format(
                stripe_plan_id_string,
                "excl_vat"
            )
        return stripe_plan_id_string

    @staticmethod
    def get_vm_config_from_stripe_id(stripe_id):
        """
        Given a string like "dcl-v1-cpu-2-ram-5gb-ssd-10gb" return different
        configuration params as a dict

        :param stripe_id|str
        :return: dict
        """
        pattern = re.compile(r'^dcl-v(\d+)-cpu-(\d+)-ram-(\d+\.?\d*)gb-ssd-(\d+)gb-?(\d*\.?\d*)(chf)?$')
        match_res = pattern.match(stripe_id)
        if match_res is not None:
            price = None
            try:
                price=match_res.group(5)
            except IndexError as ie:
                logger.debug("Did not find price in {}".format(stripe_id))
            return {
                'version': match_res.group(1),
                'cores': match_res.group(2),
                'ram': match_res.group(3),
                'ssd': match_res.group(4),
                'price': price
            }


    @staticmethod
    def get_stripe_plan_name(cpu, memory, disk_size, price, excl_vat=True):
        """
        Returns the Stripe plan name
        :return:
        """
        if excl_vat:
            return "{cpu} Cores, {memory} GB RAM, {disk_size} GB SSD, " \
                   "{price} CHF Excl. VAT".format(
                cpu=cpu,
                memory=memory,
                disk_size=disk_size,
                price=round(price, 2)
            )
        else:
            return "{cpu} Cores, {memory} GB RAM, {disk_size} GB SSD, " \
                   "{price} CHF".format(
                        cpu=cpu,
                        memory=memory,
                        disk_size=disk_size,
                        price=round(price, 2)
                    )

    @handleStripeError
    def set_subscription_meta_data(self, subscription_id, meta_data):
        """
        Adds VM metadata to a subscription
        :param subscription_id: Stripe identifier for the subscription
        :param meta_data: A dict of meta data to be added
        :return:
        """
        subscription = stripe.Subscription.retrieve(subscription_id)
        subscription.metadata = meta_data
        subscription.save()

    @handleStripeError
    def get_or_create_tax_id_for_user(self, stripe_customer_id, vat_number,
                                      type="eu_vat", country=""):
        tax_ids_list = stripe.Customer.list_tax_ids(
            stripe_customer_id,
            limit=100,
        )
        for tax_id_obj in tax_ids_list.data:
            if self.compare_vat_numbers(tax_id_obj.value, vat_number):
                logger.debug("tax id obj exists already")
                return tax_id_obj
            else:
                logger.debug(
                    "{val1} is not equal to {val2} or {con1} not same as "
                    "{con2}".format(val1=tax_id_obj.value, val2=vat_number,
                                    con1=tax_id_obj.country.lower(),
                                    con2=country.lower().strip()))
        logger.debug(
            "tax id obj does not exist for {val}. Creating a new one".format(
                val=vat_number
            ))
        tax_id_obj = stripe.Customer.create_tax_id(
            stripe_customer_id,
            type=type,
            value=vat_number,
        )
        return tax_id_obj

    @handleStripeError
    def get_payment_intent(self, amount, customer):
        """	Create a stripe PaymentIntent of the given amount and return it
            :param amount: the amount of payment_intent
            :return:
        """
        payment_intent_obj = stripe.PaymentIntent.create(
            amount=amount,
            currency='chf',
            customer=customer,
            setup_future_usage='off_session'
        )
        return payment_intent_obj

    @handleStripeError
    def get_available_payment_methods(self, customer):
        """	Retrieves all payment methods of the given customer
            :param customer: StripeCustomer object
            :return: a list of available payment methods
        """
        return_list = []
        if customer is None:
            return return_list
        cu = stripe.Customer.retrieve(customer.stripe_id)
        pms = stripe.PaymentMethod.list(
            customer=customer.stripe_id,
            type="card",
        )
        default_source = None
        if cu.default_source:
            default_source = cu.default_source
        else:
            default_source = cu.invoice_settings.default_payment_method
        for pm in pms.data:
            return_list.append({
                'last4': pm.card.last4, 'brand': pm.card.brand, 'id': pm.id,
                'exp_year': pm.card.exp_year,
                'exp_month': '{:02d}'.format(pm.card.exp_month),
                'preferred': pm.id == default_source
            })
        return return_list

    def compare_vat_numbers(self, vat1, vat2):
        _vat1 = vat1.replace(" ", "").replace(".", "").replace("-","")
        _vat2 = vat2.replace(" ", "").replace(".", "").replace("-","")
        return True if _vat1 == _vat2 else False
