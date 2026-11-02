FROM python:3.12-alpine3.20

WORKDIR /usr/src/app

RUN apk add --update --no-cache \
    git \
    build-base \
    python3-dev \
    libpq-dev \
    jpeg-dev \
    libxml2-dev \
    libxslt-dev \
    zlib-dev \
    libffi-dev \
    && rm -rf /var/cache/apk/*

COPY requirements.txt ./

# Pillow seems to need LIBRARY_PATH set as follows:  (see: https://github.com/python-pillow/Pillow/issues/1763#issuecomment-222383534)
RUN LIBRARY_PATH=/lib:/usr/lib /bin/sh -c "pip install --no-cache-dir -r requirements.txt"

COPY ./ .
COPY entrypoint.sh /

# Static files are collected at build time into /app/static (served by the hosting).
# The settings need these values to load; the real ones come at run time.
ENV STATIC_ROOT=/app/static
RUN CACHE_URL=locmem:// OPENNEBULA_DOMAIN=test_domain \
    OPENNEBULA_USERNAME=build OPENNEBULA_PASSWORD=build OPENNEBULA_PROTOCOL=http \
    OPENNEBULA_PORT=2633 OPENNEBULA_ENDPOINT=/RPC2 DJANGO_SECRET_KEY=build UNGLEICH_SITE_CONFIGS='{}' LDAP_CUSTOMER_GROUP_ID=0 \
    LDAP_DEFAULT_START_UID=0 PRE_EU_VAT_RATE=0 VM_BASE_PRICE=0 \
    RECAPTCHA_PUBLIC_KEY=build RECAPTCHA_PRIVATE_KEY=build \
    python manage.py collectstatic --noinput -v0

ENTRYPOINT ["/entrypoint.sh" ]
