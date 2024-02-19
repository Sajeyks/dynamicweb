# FROM python:3.10.0-alpine3.15
FROM python:3.5-alpine3.12

WORKDIR /usr/src/app

RUN apk add --update --no-cache \
    git \
    build-base \
    openldap-dev \
    python3-dev \
    postgresql-dev \
    jpeg-dev \
    libxml2-dev \
    libxslt-dev \
    libmemcached-dev \
    zlib-dev \
    && rm -rf /var/cache/apk/*

## For alpine 3.15 replace postgresql-dev with libpq-dev

# FIX https://github.com/python-ldap/python-ldap/issues/432
RUN echo 'INPUT ( libldap.so )' > /usr/lib/libldap_r.so

COPY requirements.txt ./

# Pillow seems to need LIBRARY_PATH set as follows:  (see: https://github.com/python-pillow/Pillow/issues/1763#issuecomment-222383534)
RUN LIBRARY_PATH=/lib:/usr/lib /bin/sh -c "pip install --no-cache-dir -r requirements.txt"

COPY ./ .
