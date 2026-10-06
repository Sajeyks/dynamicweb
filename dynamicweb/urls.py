from cms.models.pagemodel import Page
from django.urls import include, re_path
from django.contrib import admin
from django.contrib.sites.models import Site
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.views import i18n, static as static_view

from django.conf import settings
from hosting.views import (
    RailsHostingView, DjangoHostingView, NodeJSHostingView
)
from datacenterlight.views import PaymentOrderView
from webhook import views as webhook_views
from membership import urls as membership_urls
from ungleich_page.views import LandingView
from django.views.generic import RedirectView
from django.urls import reverse_lazy
import debug_toolbar

urlpatterns = [
    re_path(r'^index.html$', LandingView.as_view()),
    re_path(r'^open_api/',
        include('opennebula_api.urls', namespace='opennebula_api')),
    re_path(r'^railshosting/', RailsHostingView.as_view(),
        name="rails.hosting"),
    re_path(r'^nodehosting/', NodeJSHostingView.as_view(),
        name="node.hosting"),
    re_path(r'^djangohosting/', DjangoHostingView.as_view(),
        name="django.hosting"),
    re_path(r'^nosystemd/', include('nosystemd.urls', namespace="nosystemd")),
    re_path(r'^taggit_autosuggest/', include('taggit_autosuggest.urls')),
    re_path(r'^jsi18n/(?P<packages>\S+?)/$', i18n.JavaScriptCatalog.as_view()),
    re_path(r'^product/(?P<product_slug>[\w-]+)/$',
        PaymentOrderView.as_view(),
        name='show_product'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += i18n_patterns(
    re_path(r'^hosting/', include('hosting.urls', namespace="hosting")),
)

# note the django CMS URLs included via i18n_patterns


def home_view(request, *args, **kwargs):
    # decided per request so that importing the urlconf needs no database
    if Page.objects.filter(node__site_id=Site.objects.get_current().id).exists():
        return RedirectView.as_view(url='/cms')(request, *args, **kwargs)
    return LandingView.as_view()(request, *args, **kwargs)


urlpatterns += i18n_patterns(
    re_path(r'^admin/', admin.site.urls),
    re_path(r'^datacenterlight/',
        include('datacenterlight.urls', namespace="datacenterlight")),
    re_path(r'^hosting/', RedirectView.as_view(url=reverse_lazy('hosting:login')),
        name='redirect_hosting_login'),
    re_path(r'^alplora/', include('alplora.urls', namespace="alplora")),
    re_path(r'^membership/', include(membership_urls)),
    re_path(r'^digitalglarus/',
        include('digitalglarus.urls', namespace="digitalglarus")),
    re_path(r'^cms/blog/', include('ungleich.urls', namespace='ungleich')),
    re_path(r'^blog/(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<slug>\w[-\w]*)/$',
        RedirectView.as_view(pattern_name='ungleich:post-detail')),
    re_path(r'^blog/$',
        RedirectView.as_view(url=reverse_lazy('ungleich:post-list')),
        name='blog_list_view'),
    re_path(r'^cms/', include('cms.urls')),
    re_path(r'^blog/', include('djangocms_blog.urls', namespace='djangocms_blog')),
    re_path(r'^webhooks/', webhook_views.handle_webhook),
    re_path(r'^$', home_view),
    re_path(r'^', include('ungleich_page.urls', namespace='ungleich_page')),
)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$',
        static_view.serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
]

if settings.DEBUG:
    urlpatterns += [re_path(r'^__debug__/', include(debug_toolbar.urls))]
