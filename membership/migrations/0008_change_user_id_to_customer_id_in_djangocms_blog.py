from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('membership', '0007_auto_20180213_0128'),
                    ('djangocms_blog', '0032_auto_20180109_0023'),
                    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE djangocms_blog_authorentriesplugin_authors "
            "RENAME COLUMN user_id TO customuser_id;"),
    ]
