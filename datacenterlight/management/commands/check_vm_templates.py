from django.core.management.base import BaseCommand
from opennebula_api.models import OpenNebulaManager
from datacenterlight.models import VMTemplate
from membership.models import CustomUser

from django.conf import settings
from time import sleep
import datetime
import json
import logging
import os

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Checks all VM templates to find if they can be instantiated'''

    def add_arguments(self, parser):
        parser.add_argument('user_email', type=str)

    def handle(self, *args, **options):
        result_dict = {}
        user_email = options['user_email'] if 'user_email' in options else ""

        if user_email:
            cu = CustomUser.objects.get(email=user_email)
            specs = {'cpu': 1, 'memory': 1, 'disk_size': 10}
            manager = OpenNebulaManager(email=user_email, password=cu.password)
            pub_keys = [settings.TEST_MANAGE_SSH_KEY_PUBKEY]
            PROJECT_PATH = os.path.abspath(os.path.dirname(__name__))
            if not os.path.exists("%s/outputs" % PROJECT_PATH):
                os.mkdir("%s/outputs" % PROJECT_PATH)
            for vm_template in VMTemplate.objects.all():
                vm_name = 'test-%s' % vm_template.name
                vm_id = manager.create_vm(
                    template_id=vm_template.opennebula_vm_template_id,
                    specs=specs,
                    ssh_key='\n'.join(pub_keys),
                    vm_name=vm_name
                )
                if vm_id and vm_id > 0:
                    result_dict[vm_name] = "%s OK, created VM %s" % (
                        '%s %s %s' % (vm_template.opennebula_vm_template_id,
                                      vm_template.name, vm_template.vm_type),
                        vm_id
                    )
                    self.stdout.write(self.style.SUCCESS(result_dict[vm_name]))
                    manager.delete_vm(vm_id)
                else:
                    result_dict[vm_name] = '''Error creating VM %s, template_id
                    %s %s''' % (vm_name,
                                vm_template.opennebula_vm_template_id,
                                vm_template.vm_type)
                    self.stdout.write(self.style.ERROR(result_dict[vm_name]))
                sleep(1)
            date_str = datetime.datetime.strftime(
                datetime.datetime.now(), '%Y%m%d%H%M%S'
            )
            with open("%s/outputs/check_vm_templates_%s.txt" %
                      (PROJECT_PATH, date_str),
                      'w',
                      encoding='utf-8') as f:
                f.write(json.dumps(result_dict))
        self.stdout.write(self.style.SUCCESS("Done"))
