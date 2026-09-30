from django.db import migrations

# Only rename when the old column exists: databases created from scratch
# already have customuser_id (djangocms_blog is created after AUTH_USER_MODEL
# is set), so an unconditional rename fails there.
RENAME_IF_NEEDED = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'djangocms_blog_authorentriesplugin_authors'
        AND column_name = 'user_id'
    ) THEN
        ALTER TABLE djangocms_blog_authorentriesplugin_authors
        RENAME COLUMN user_id TO customuser_id;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [('membership', '0007_auto_20180213_0128'),
                    ('djangocms_blog', '0032_auto_20180109_0023'),
                    ]

    operations = [
        migrations.RunSQL(RENAME_IF_NEEDED),
    ]
