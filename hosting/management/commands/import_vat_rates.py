from django.core.management.base import BaseCommand
import csv
from hosting.models import VATRates


class Command(BaseCommand):
    help = '''Imports VAT Rates. Assume vat rates of format https://github.com/kdeldycke/vat-rates/blob/master/vat_rates.csv'''

    def add_arguments(self, parser):
        parser.add_argument('csv_file', nargs='+', type=str)

    def handle(self, *args, **options):
        try:
            for c_file in options['csv_file']:
                print("c_file =  %s" % c_file)
                with open(c_file, mode='r') as csv_file:
                    csv_reader = csv.DictReader(csv_file)
                    line_count = 0
                    for row in csv_reader:
                        if line_count == 0:
                            line_count += 1
                        obj, created = VATRates.objects.get_or_create(
                            start_date=row["start_date"],
                            stop_date=row["stop_date"] if row["stop_date"] is not "" else None,
                            territory_codes=row["territory_codes"],
                            currency_code=row["currency_code"],
                            rate=row["rate"],
                            rate_type=row["rate_type"],
                            description=row["description"]
                        )
                        if created:
                            self.stdout.write(self.style.SUCCESS(
                                '%s. %s - %s - %s - %s' % (
                                    line_count,
                                    obj.start_date,
                                    obj.stop_date,
                                    obj.territory_codes,
                                    obj.rate
                                )
                            ))
                            line_count+=1

        except Exception as e:
            print(" *** Error occurred. Details {}".format(str(e)))
