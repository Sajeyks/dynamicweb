import logging

import stripe
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''creates webhook with the supplied arguments and returns the 
    webhook secret
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--webhook_endpoint',
            help="The url of the webhook endpoint that accepts the events "
                 "from stripe",
            dest="webhook_endpoint",
            required=False
        )
        parser.add_argument('--events_csv', dest="events_csv", required=False)
        parser.add_argument('--webhook_id', dest="webhook_id", required=False)
        parser.add_argument('--create', dest='create', action='store_true')
        parser.add_argument('--list', dest='list', action='store_true')
        parser.add_argument('--delete', dest='delete', action='store_true')

    def handle(self, *args, **options):
        wep_exists = False
        if options['list']:
            logger.debug("Listing webhooks")
            we_list = stripe.WebhookEndpoint.list(limit=100)
            for wep in we_list.data:
                msg = wep.id + " -- " + ",".join(wep.enabled_events)
                logger.debug(msg)
                self.stdout.write(
                    self.style.SUCCESS(msg)
                )
        elif options['delete']:
            logger.debug("Deleting webhook")
            if 'webhook_id' in options:
                stripe.WebhookEndpoint.delete(options['webhook_id'])
                msg = "Deleted " + options['webhook_id']
                logger.debug(msg)
                self.stdout.write(
                    self.style.SUCCESS(msg)
                )
            else:
                msg = "Supply webhook_id to delete a webhook"
                logger.debug(msg)
                self.stdout.write(
                    self.style.SUCCESS(msg)
                )
                exit(0)
        elif options['create']:
            logger.debug("Creating webhook")
            try:
                we_list = stripe.WebhookEndpoint.list(limit=100)
                for wep in we_list.data:
                    if set(wep.enabled_events) == set(options['events_csv'].split(",")):
                        if wep.url == options['webhook_endpoint']:
                            logger.debug("We have this webhook already")
                            wep_exists = True
                            break
                if wep_exists is False:
                    logger.debug(
                        "No webhook exists for {} at {}. Creatting a new endpoint "
                        "now".format(
                            options['webhook_endpoint'], options['events_csv']
                        )
                    )
                    wep = stripe.WebhookEndpoint.create(
                        url=options['webhook_endpoint'],
                        enabled_events=options['events_csv'].split(",")
                    )
                    self.stdout.write(
                        self.style.SUCCESS('Creation successful. '
                                           'webhook_secret = %s' % wep.secret)
                    )
            except Exception as e:
                print(" *** Error occurred. Details {}".format(str(e)))
