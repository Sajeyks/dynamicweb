FROM python:3.10.0-alpine3.15

WORKDIR /usr/src/app

RUN apk add --update --no-cache \
    git \
    build-base \
    openldap-dev\
    python3-dev\
    && rm -rf /var/cache/apk/*

# FIX https://github.com/python-ldap/python-ldap/issues/432
RUN echo 'INPUT ( libldap.so )' > /usr/lib/libldap_r.so

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY ./ .
