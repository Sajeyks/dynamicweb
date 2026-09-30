import json

from django.conf import settings
from django.http import HttpResponse


class MultipleProxyMiddleware(object):
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


class DevSiteSwitcherMiddleware(object):
    """
    Dev/test only (enabled from settings/local.py, i.e. DEBUG=True).

    The project picks a site from the request's Host header. To test every
    site from a single address without DNS or /etc/hosts entries, visit
    http://<server>:8000/?site=datacenterlight.ch once; the choice is kept in
    a cookie. ?site= (empty) clears it.
    """
    COOKIE = 'dev_site'

    def process_request(self, request):
        if request.path == '/dev-sites/':
            return self.sites_page()
        if 'site' in request.GET:
            site = request.GET['site'].strip()
        else:
            site = request.COOKIES.get(self.COOKIE, '')
        request.META['DEV_SITE_SWITCH'] = site
        if site:
            request.META['HTTP_HOST'] = site
            request.META.pop('HTTP_X_FORWARDED_HOST', None)

    def process_response(self, request, response):
        if 'site' in request.GET:
            site = request.META.get('DEV_SITE_SWITCH', '')
            if site:
                response.set_cookie(self.COOKIE, site)
            else:
                response.delete_cookie(self.COOKIE)
        return response

    def sites_page(self):
        """A page listing every configured site as a link, on any host"""
        try:
            domains = sorted(
                d for d in json.loads(settings.UNGLEICH_SITE_CONFIGS)
                if ':' not in d)
        except ValueError:
            domains = []
        items = ''.join(
            '<li><a href="/?site={0}">{0}</a></li>'.format(d) for d in domains)
        return HttpResponse(
            '<!doctype html><title>Test sites</title>'
            '<h1>Test sites</h1><p>Click a site to browse it; '
            '<a href="/?site=">clear</a> the choice.</p><ul>{}</ul>'.format(
                items))
