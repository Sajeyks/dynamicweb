from django.core.management.base import BaseCommand
from datacenterlight.tasks import handle_metadata_and_emails
from opennebula_api.models import OpenNebulaManager
import logging
import json

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''Updates the DB after manual creation of VM'''

    def add_arguments(self, parser):
        parser.add_argument('vm_id', type=int)
        parser.add_argument('order_id', type=int)
        parser.add_argument('user', type=str)
        parser.add_argument('specs', type=str)
        parser.add_argument('template', type=str)

    def handle(self, *args, **options):
        vm_id = options['vm_id']
        order_id = options['order_id']
        user_str = options['user']
        specs_str = options['specs']
        template_str = options['template']

        json_acceptable_string = user_str.replace("'", "\"")
        user_dict = json.loads(json_acceptable_string)

        json_acceptable_string = specs_str.replace("'", "\"")
        specs = json.loads(json_acceptable_string)

        json_acceptable_string = template_str.replace("'", "\"")
        template = json.loads(json_acceptable_string)
        if vm_id <= 0:
            self.stdout.write(self.style.ERROR(
                'vm_id can\'t be less than or 0. Given: %s' % vm_id))
            return
        if vm_id <= 0:
            self.stdout.write(self.style.ERROR(
                'order_id can\'t be less than or 0. Given: %s' % vm_id))
            return
        if specs_str is None or specs_str == "":
            self.stdout.write(
                self.style.ERROR('specs can\'t be empty or None'))
            return

        user = {
            'name': user_dict['name'],
            'email': user_dict['email'],
            'username': user_dict['username'],
            'pass': user_dict['pass'],
            'request_scheme': user_dict['request_scheme'],
            'request_host': user_dict['request_host'],
            'language': user_dict['language'],
        }

        on_user = user.get('username')
        on_pass = user.get('pass')

        # Create OpenNebulaManager
        self.style.SUCCESS(
            'Connecting using %s %s' % (on_user, on_pass)
        )
        manager = OpenNebulaManager(email=on_user, password=on_pass)
        handle_metadata_and_emails(order_id, vm_id, manager, user, specs,
                                   template)
        self.stdout.write(
            self.style.SUCCESS(
                'Done handling metadata and emails for %s %s %s' % (
                    order_id,
                    vm_id,
                    str(user)
                )
           )
        )
