from datetime import datetime
from time import sleep

from celery import current_task
from celery.exceptions import MaxRetriesExceededError
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.utils import translation
from django.utils.translation import ugettext_lazy as _

from dynamicweb.celery import app
from hosting.models import HostingOrder
from membership.models import CustomUser
from opennebula_api.models import OpenNebulaManager
from opennebula_api.serializers import VirtualMachineSerializer
from utils.hosting_utils import (
    get_all_public_keys, get_or_create_vm_detail
)
from utils.mailer import BaseEmail
from utils.stripe_utils import StripeUtils
from .models import VMPricing

logger = get_task_logger(__name__)


def retry_task(task, exception=None):
    """Retries the specified task using a "backing off countdown",
    meaning that the interval between retries grows exponentially
    with every retry.

    Arguments:
        task:
            The task to retry.

        exception:
            Optionally, the exception that caused the retry.
    """

    def backoff(attempts):
        return 2 ** attempts

    kwargs = {
        'countdown': backoff(task.request.retries),
    }

    if exception:
        kwargs['exc'] = exception

    raise task.retry(**kwargs)


@app.task(bind=True, max_retries=settings.CELERY_MAX_RETRIES)
def create_vm_task(self, vm_template_id, user, specs, template, order_id):
    logger.debug(
        "Running create_vm_task on {}".format(current_task.request.hostname))
    vm_id = None
    try:
        final_price = (
            specs.get('total_price') if 'total_price' in specs
            else specs.get('price')
        )

        if 'pass' in user:
            on_user = user.get('email')
            on_pass = user.get('pass')
            logger.debug("Using user {user} to create VM".format(user=on_user))
            vm_name = None
        else:
            on_user = settings.OPENNEBULA_USERNAME
            on_pass = settings.OPENNEBULA_PASSWORD
            logger.debug("Using OpenNebula admin user to create VM")
            vm_name = "{email}-{template_name}-{date}".format(
                email=user.get('email'),
                template_name=template.get('name'),
                date=int(datetime.now().strftime("%s")))

        # Create OpenNebulaManager
        manager = OpenNebulaManager(email=on_user, password=on_pass)

        custom_user = CustomUser.objects.get(email=user.get('email'))
        pub_keys = get_all_public_keys(custom_user)
        if manager.email != settings.OPENNEBULA_USERNAME:
            manager.save_key_in_opennebula_user('\n'.join(pub_keys))
        vm_id = manager.create_vm(
            template_id=vm_template_id,
            specs=specs,
            ssh_key='\n'.join(pub_keys),
            vm_name=vm_name
        )

        if vm_id is None:
            raise Exception("Could not create VM")

        # Update HostingOrder with the created vm_id
        hosting_order = HostingOrder.objects.filter(id=order_id).first()
        error_msg = None

        try:
            hosting_order.vm_id = vm_id
            hosting_order.save()
            logger.debug(
                "Updated hosting_order {} with vm_id={}".format(
                    hosting_order.id, vm_id
                )
            )
        except Exception as ex:
            error_msg = (
                "HostingOrder with id {order_id} not found. This means that "
                "the hosting order was not created and/or it is/was not "
                "associated with VM with id {vm_id}. Details {details}".format(
                    order_id=order_id, vm_id=vm_id, details=str(ex)
                )
            )
            logger.error(error_msg)

        stripe_utils = StripeUtils()
        result = stripe_utils.set_subscription_metadata(
            subscription_id=hosting_order.subscription_id,
            metadata={"VM_ID": str(vm_id)}
        )

        if result.get('error') is not None:
            emsg = "Could not update subscription metadata for {sub}".format(
                sub=hosting_order.subscription_id
            )
            logger.error(emsg)
            if error_msg:
                error_msg += ". " + emsg
            else:
                error_msg = emsg

        vm = VirtualMachineSerializer(manager.get_vm(vm_id)).data

        context = {
            'name': user.get('name'),
            'email': user.get('email'),
            'cores': specs.get('cpu'),
            'memory': specs.get('memory'),
            'storage': specs.get('disk_size'),
            'price': final_price,
            'template': template.get('name'),
            'vm_name': vm.get('name'),
            'vm_id': vm['vm_id'],
            'order_id': order_id
        }

        if error_msg:
            context['errors'] = error_msg
        if 'pricing_name' in specs:
            context['pricing'] = str(VMPricing.get_vm_pricing_by_name(
                name=specs['pricing_name']
            ))
        email_data = {
            'subject': settings.DCL_TEXT + " Order from %s" % context['email'],
            'from_email': settings.DCL_SUPPORT_FROM_ADDRESS,
            'to': ['info@ungleich.ch'],
            'body': "\n".join(
                ["%s=%s" % (k, v) for (k, v) in context.items()]),
            'reply_to': [context['email']],
        }
        email = EmailMessage(**email_data)
        email.send()

        if 'pass' in user:
            lang = 'en-us'
            if user.get('language') is not None:
                logger.debug(
                    "Language is set to {}".format(user.get('language')))
                lang = user.get('language')
            translation.activate(lang)
            # Send notification to the user as soon as VM has been booked
            context = {
                'base_url': "{0}://{1}".format(user.get('request_scheme'),
                                               user.get('request_host')),
                'order_url': reverse('hosting:orders',
                                     kwargs={'pk': order_id}),
                'page_header': _(
                    'Your New VM %(vm_name)s at Data Center Light') % {
                                   'vm_name': vm.get('name')},
                'vm_name': vm.get('name')
            }
            email_data = {
                'subject': context.get('page_header'),
                'to': user.get('email'),
                'context': context,
                'template_name': 'new_booked_vm',
                'template_path': 'hosting/emails/',
                'from_address': settings.DCL_SUPPORT_FROM_ADDRESS,
            }
            email = BaseEmail(**email_data)
            email.send()

            logger.debug("New VM ID is {vm_id}".format(vm_id=vm_id))
            get_or_create_vm_detail(custom_user, manager, vm_id)
    except Exception as e:
        logger.error(str(e))
        try:
            retry_task(self)
        except MaxRetriesExceededError:
            msg_text = 'Finished {} retries for create_vm_task'.format(
                self.request.retries)
            logger.error(msg_text)
            # Try sending email and stop
            email_data = {
                'subject': '{} CELERY TASK ERROR: {}'.format(settings.DCL_TEXT,
                                                             msg_text),
                'from_email': current_task.request.hostname,
                'to': settings.DCL_ERROR_EMAILS_TO_LIST,
                'body': ',\n'.join(str(i) for i in self.request.args)
            }
            email = EmailMessage(**email_data)
            email.send()
            return

    return vm_id


@app.task(bind=True, max_retries=settings.CELERY_MAX_RETRIES)
def save_ssh_key_in_vm_template_task(self, user, vm_id, ssh_key_str):
    logger.debug("Inside save_ssh_key_in_vm_template_task %s" % vm_id)

    on_user = user.get('email')
    on_pass = user.get('pass')

    if on_user is None or on_pass is None:
        logger.error(
            "Either email or password not supplied. Can't save ssh key"
        )
        return

    manager = OpenNebulaManager(email=on_user, password=on_pass)

    # poweroff the vm
    vm = manager.power_off_vm(vm_id)

    powered_off = False
    for t in range(15):
        vm = manager.get_vm(vm_id)
        if vm.str_state == 'POWEROFF':
            logger.debug(
                "VM %s has been powered off. Now adding ssh keys" % vm.id
            )
            powered_off = True
            break
        else:
            logger.debug(
                "VM {} has state {}. Waiting 2 more seconds to see if it " 
                "powers off".format(vm.id, vm.str_state)
            )
            sleep(2)

    if powered_off:
        logger.debug(
            "VM %s was powered off by api call" % vm.id
        )
        if manager.save_key_in_vm_template(vm_id=vm_id, ssh_key=ssh_key_str) > 0:
            logger.debug(
                "Added ssh_keys of user %s to VM %s successfully" %
                (on_user, vm_id)
            )
            manager.resume(vm_id)
            lang = 'en-us'
            if user.get('language') is not None:
                logger.debug(
                    "Language is set to {}".format(user.get('language')))
                lang = user.get('language')
            translation.activate(lang)
            # Send notification to the user as soon as VM has been booked
            context = {
                'page_header': str(_("Adding of SSH key completed")),
                'base_url': "{0}://{1}".format(user.get('request_scheme'),
                                               user.get('request_host')),
                'vm_detail_url': reverse('hosting:virtual_machines',
                                     kwargs={'pk': vm_id}),
                'vm_name': vm.name
            }
            email_data = {
                'subject': context.get('page_header'),
                'to': user.get('email'),
                'context': context,
                'template_name': 'ssh_key_added_to_vm',
                'template_path': 'hosting/emails/',
                'from_address': settings.DCL_SUPPORT_FROM_ADDRESS,
            }
            email = BaseEmail(**email_data)
            email.send()
        else:
            logger.error(
                "There was an error updating ssh keys of the VM %s" % vm_id
            )
    else:
        logger.error(
            "VM {} did not poweroff within 30 seconds after the poweroff api "
            "call. Please, ask the admin to poweroff and add the key "
            "manually.".format(vm_id)
        )
