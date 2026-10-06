from django.db import migrations


class Migration(migrations.Migration):
    """Django 2.1+ creates view_* permissions itself; the custom ones clash."""

    dependencies = [
        ('hosting', '0066_auto_20230727_0812'),
    ]

    operations = [
        migrations.AlterModelOptions(name=name, options={})
        for name in ('hostingorder', 'hostingbill', 'monthlyhostingbill',
                     'hostingbilllineitem', 'usercarddetail')
    ]
