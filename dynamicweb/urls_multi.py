from django.conf import settings
from django.urls import include, re_path
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.views import static as static_view
from django.views.generic import RedirectView

urlpatterns = i18n_patterns(
    re_path(r'^admin/', admin.site.urls),
    re_path(r'^cms/', include('cms.urls')),
    re_path(r'^$', RedirectView.as_view(url='/cms')),
)

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$',
        static_view.serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
]
