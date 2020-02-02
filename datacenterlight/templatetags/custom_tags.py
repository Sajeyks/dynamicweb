import datetime
import logging

from django import template
from django.core.urlresolvers import resolve, reverse
from django.utils.safestring import mark_safe
from django.utils.translation import activate, get_language, ugettext_lazy as _

from hosting.models import GenericProduct
from utils.hosting_utils import get_ip_addresses

logger = logging.getLogger(__name__)

register = template.Library()


@register.simple_tag(takes_context=True)
def change_lang(context, lang=None, *args, **kwargs):

    path = context['request'].path
    url_parts = resolve(path)

    url = path
    cur_language = get_language()
    try:
        activate(lang)
        url = reverse(url_parts.view_name, kwargs=url_parts.kwargs)
    finally:
        activate(cur_language)

    return "%s" % url


@register.filter('get_value_from_dict')
def get_value_from_dict(dict_data, key):
    """
    usage example {{ your_dict|get_value_from_dict:your_key }}
    """
    if key:
        return dict_data.get(key)
    else:
        return ""


@register.filter('multiply')
def multiply(value, arg):
    """
    usage: {{ quantity|multiply:price }}
    :param value:
    :param arg:
    :return:
    """
    return value * arg


@register.filter('escaped_line_break')
def escaped_line_break(value):
    """
    usage: {{ text|escaped_line_break }}
    :param value:
    :return:
    """
    return value.replace("\\n", "\n")


@register.filter('get_line_item_from_stripe_invoice')
def get_line_item_from_stripe_invoice(invoice):
    """
    Returns ready-to-use "html" line item to be shown for an invoice in the
    invoice list page

    :param invoice: the stripe Invoice object
    :return:
    """
    start_date = 0
    end_date = 0
    is_first = True
    vm_id = -1
    plan_name = ""
    for line_data in invoice["lines"]["data"]:
        if is_first:
            plan_name = line_data.plan.name
            start_date = line_data.period.start
            end_date = line_data.period.end
            is_first = False
            if hasattr(line_data.metadata, "VM_ID"):
                vm_id = line_data.metadata.VM_ID
        else:
            if line_data.period.start < start_date:
                start_date = line_data.period.start
            if line_data.period.end > end_date:
                end_date = line_data.period.end
            if hasattr(line_data.metadata, "VM_ID"):
                vm_id = line_data.metadata.VM_ID

    try:
        vm_id = int(vm_id)
    except ValueError as ve:
        print(str(ve))
    if invoice["lines"]["data"]:
        return mark_safe("""
                    <td class="xs-td-inline">{vm_id}</td>
                    <td class="xs-td-inline">{ip_addresses}</td>
                    <td class="xs-td-inline">{period}</td>
                    <td class="xs-td-inline">{total}</td>
                    <td class="text-right last-td">
                        <a class="btn btn-order-detail" href="{stripe_invoice_url}" target="_blank">{see_invoice_text}</a>
                    </td>
        """.format(
            vm_id=vm_id if vm_id > 0 else "",
            ip_addresses=mark_safe(get_ip_addresses(vm_id)) if vm_id > 0 else
            mark_safe(get_product_name(plan_name)),
            period=mark_safe("%s &mdash; %s" % (
                datetime.datetime.fromtimestamp(start_date).strftime('%Y-%m-%d'),
                datetime.datetime.fromtimestamp(end_date).strftime('%Y-%m-%d'))),
            total='%.2f' % (invoice.total/100),
            stripe_invoice_url=invoice.hosted_invoice_url,
            see_invoice_text=_("See Invoice")
        ))
    else:
        return ""


def get_product_name(plan_name):
    product_name = ""
    if plan_name and plan_name.startswith("generic-"):
        first_index_hyphen = plan_name.index("-") + 1
        product_id = plan_name[first_index_hyphen:
        (plan_name[first_index_hyphen:].index("-")) + first_index_hyphen]
        try:
            product = GenericProduct.objects.get(id=product_id)
            product_name = product.product_name
        except GenericProduct.DoesNotExist as dne:
            logger.error("Generic product id=%s does not exist" % product_id)
            product_name = plan_name
        except GenericProduct.MultipleObjectsReturned as mor:
            logger.error("Multiple products with id=%s exist" % product_id)
            product_name = "Unknown"
    else:
        logger.debug("Product name for plan %s does not exist" % plan_name)
    return product_name
