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

ENTRYPOINT ["/entrypoint.sh" ]
