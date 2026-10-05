"""
Smoke test for a running stack: opens every site and the admin login.

    docker compose exec web python smoke_test.py [base_url]

Needs no extra packages, so it runs the same on every Python/Django version.
Exits non-zero if anything fails. Expects the sample data (SEED_DUMMY_DATA).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

from utils.sample_sites import SITE_TEXTS

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
ADMIN = ('dummy-admin@example.com',
         os.environ.get('DUMMY_ADMIN_PASSWORD') or 'dummy-admin')
SUB_PAGES = ['about', 'services', 'pricing', 'contact']
failures = []


def fetch(opener, path, host, data=None):
    request = urllib.request.Request(BASE + path, data=data)
    request.add_header('Host', host)
    try:
        response = opener.open(request, timeout=60)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace'), path
    return (response.status if hasattr(response, 'status')
            else response.getcode(),
            response.read().decode('utf-8', 'replace'), response.geturl())


def check(name, ok, detail=''):
    print('{} {}{}'.format('ok  ' if ok else 'FAIL', name,
                           '' if ok else '  -> ' + detail))
    if not ok:
        failures.append(name)


def sites():
    configs = json.loads(os.environ.get('UNGLEICH_SITE_CONFIGS') or '{}')
    return sorted(d for d in configs if ':' not in d)


def main():
    for domain in sites():
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()))
        name, tagline = SITE_TEXTS.get(domain, (domain, ''))
        status, body, _ = fetch(opener, '/', domain)
        check('{} /'.format(domain), status == 200, 'status %s' % status)
        status, body, _ = fetch(opener, '/en-us/cms/', domain)
        check('{} home'.format(domain),
              status == 200 and name in body and tagline in body,
              'status %s, content missing' % status)
        for slug in SUB_PAGES:
            status, _, _ = fetch(opener, '/en-us/cms/%s/' % slug, domain)
            check('{} {}'.format(domain, slug), status == 200,
                  'status %s' % status)

    # admin login on the first site
    domain = sites()[0]
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    status, body, _ = fetch(opener, '/en-us/admin/login/', domain)
    token = re.search(r"name=.csrfmiddlewaretoken. value=.([^'\"]+)", body)
    check('admin login page', status == 200 and token, 'status %s' % status)
    if token:
        form = urllib.parse.urlencode({
            'csrfmiddlewaretoken': token.group(1), 'username': ADMIN[0],
            'password': ADMIN[1], 'next': '/en-us/admin/'}).encode()
        status, body, url = fetch(
            opener, '/en-us/admin/login/', domain, data=form)
        check('admin login works',
              status == 200 and 'login' not in url, 'status %s, ended on %s' % (status, url))

    print('\n{} failure(s)'.format(len(failures)))
    sys.exit(1 if failures else 0)


main()
