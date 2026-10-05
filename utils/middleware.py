import json
import re

from django.conf import settings
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin

from djangocms_multisite.middleware import CMSMultiSiteMiddleware as _CMSMultiSite


class CMSMultiSiteMiddleware(MiddlewareMixin, _CMSMultiSite):
    """The package's middleware is old-style (no get_response); adapt it"""


class MultipleProxyMiddleware(MiddlewareMixin):
    FORWARDED_FOR_FIELDS = [
        'HTTP_X_FORWARDED_FOR',
        'HTTP_X_FORWARDED_HOST',
        'HTTP_X_FORWARDED_SERVER',
    ]

    def process_request(self, request):
        """
        Rewrites the proxy headers so that only the most
        recent proxy is used.
        """
        for field in self.FORWARDED_FOR_FIELDS:
            if field in request.META:
                if ',' in request.META[field]:
                    parts = request.META[field].split(',')
                    request.META[field] = parts[-1].strip()


class DevSiteSwitcherMiddleware(MiddlewareMixin):
    """
    Dev/test only (enabled from settings/local.py, i.e. DEBUG=True).

    The project picks a site from the request's Host header. To test every
    site from one server without DNS or /etc/hosts entries, the site is
    chosen, in this order, from:

    1. the host: "<domain>.<anything>", e.g. digitalglarus.ch.localhost:8000
       or digitalglarus.ch.203.0.113.5.sslip.io:8000. Every site is then its
       own browser origin, so tabs and cookies never interfere. Preferred.
    2. ?site=<domain>, remembered in a cookie ("?site=" clears it). Redirects
       keep the parameter so the choice survives them.
    3. the cookie set by 2.

    /dev-sites/ lists every configured site as a link.
    """
    COOKIE = 'dev_site'

    def domains(self):
        try:
            found = [d for d in json.loads(settings.UNGLEICH_SITE_CONFIGS)
                     if ':' not in d]
        except ValueError:
            found = []
        return sorted(found, key=len, reverse=True)

    def site_from_host(self, request):
        host = request.get_host().split(':')[0].lower()
        for domain in self.domains():
            if host == domain or host.startswith(domain + '.'):
                return domain
        return ''

    def process_request(self, request):
        if request.path == '/dev-sites/':
            return self.sites_page(request)
        site = self.site_from_host(request)
        if not site:
            if 'site' in request.GET:
                site = request.GET['site'].strip()
            else:
                site = request.COOKIES.get(self.COOKIE, '')
        request.META['DEV_SITE_SWITCH'] = site
        if site:
            request.META['HTTP_HOST'] = site
            request.META.pop('HTTP_X_FORWARDED_HOST', None)

    def process_response(self, request, response):
        site = request.META.get('DEV_SITE_SWITCH', '')
        # dev only: never let a browser reuse a page or redirect from another
        # site, and show which site the server picked (see browser dev tools)
        response['Cache-Control'] = 'no-store'
        response['X-Dev-Site'] = site or '(default)'
        if 'site' not in request.GET:
            return response
        if site:
            response.set_cookie(self.COOKIE, site)
            location = response.get('Location', '')
            if response.status_code in (301, 302) and location.startswith('/') \
                    and 'site=' not in location:
                response['Location'] = location + (
                    '&' if '?' in location else '?') + 'site=' + site
        else:
            response.delete_cookie(self.COOKIE)
        return response

    def sites_page(self, request):
        """A page listing every configured site as a link, on any host"""
        host, _, port = request.get_host().partition(':')
        port = ':' + port if port else ''
        # opened on a site's own address (e.g. blog.ungleich.ch.localhost):
        # drop that site's prefix so links are not nested
        for domain in self.domains():
            if host.lower().startswith(domain + '.'):
                host = host[len(domain) + 1:]
                break
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
            # an IP has no subdomains; sslip.io resolves <anything>.<ip>.sslip.io
            base = host + '.sslip.io'
        else:
            base = host
        items = ''.join(
            '<li><a href="http://{0}.{1}{2}/">{0}</a></li>'.format(
                d, base, port) for d in sorted(self.domains()))
        return HttpResponse(
            '<!doctype html><title>Test sites</title>'
            '<h1>Test sites</h1><p>Each site opens on its own address, so '
            'you can open several at once.</p><ul>{}</ul>'
            '<p>Fallback without wildcard names: '
            '<code>/?site=&lt;domain&gt;</code> (<a href="/?site=">clear</a>)'
            '</p>'.format(items))
