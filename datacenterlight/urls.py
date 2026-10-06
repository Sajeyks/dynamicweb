from django.urls import re_path
from django.views.generic import TemplateView, RedirectView

from utils.views import AskSSHKeyView
from .views import (
    IndexView, PaymentOrderView, OrderConfirmationView,
    WhyDataCenterLightView, ContactUsView
)

app_name = 'datacenterlight'

urlpatterns = [
    re_path(r'^$', IndexView.as_view(), name='index'),
    re_path(r'^t/$', IndexView.as_view(), name='index_t'),
    re_path(r'^g/$', IndexView.as_view(), name='index_g'),
    re_path(r'^f/$', IndexView.as_view(), name='index_f'),
    re_path(r'^l/$', IndexView.as_view(), name='index_l'),
    re_path(r'^new/$', RedirectView.as_view(url='/cms/'),
        name='cms_index'),
    re_path(r'^whydatacenterlight/?$', WhyDataCenterLightView.as_view(),
        name='whydatacenterlight'),
    re_path(r'^payment/?$', PaymentOrderView.as_view(), name='payment'),
    re_path(r'^order-confirmation/?$', OrderConfirmationView.as_view(),
        name='order_confirmation'),
    re_path(r'^add-ssh-key/?$', AskSSHKeyView.as_view(),
        name='add_ssh_key'),
    re_path(r'^contact/?$', ContactUsView.as_view(), name='contact_us'),
    re_path(r'glasfaser/?$',
        TemplateView.as_view(template_name='ungleich_page/glasfaser.html'),
        name='glasfaser'),
]
