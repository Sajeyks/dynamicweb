#!/bin/sh

set -uex

cd /usr/src/app/
cat > dynamicweb/settings/dynamic.py <<EOF
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': '${POSTGRES_DB}',
        'USER': '${POSTGRES_USER}',
        'PASSWORD': '${POSTGRES_PASSWORD}',
        'HOST': '${POSTGRES_HOST}',
        'PORT': '5432',
    }
}
EOF

exec "$@"
