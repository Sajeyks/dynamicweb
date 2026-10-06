from django.urls import re_path
from .views import ContactView, LandingView
from django.utils.translation import gettext_lazy as _

app_name = 'ungleich_page'

urlpatterns = [
    re_path(r'^$', LandingView.as_view(), name='landing'),
    # re_path(r'^ungleich_page/?$', LandingView.as_view(), name='landing'),
    re_path(_(r'contact/$'), ContactView.as_view(), name='contact'),
]
