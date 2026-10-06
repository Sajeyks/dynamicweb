from django.urls import re_path
from django.contrib.auth import views as auth_views

from .views import LandingView, LoginView, SignupView, PasswordResetView,\
    PasswordResetConfirmView, DonationView, DonationDetailView, ChangeDonatorStatusDetailView,\
    DonatorStatusDetailView, DonationListView

app_name = 'nosystemd'

urlpatterns = [
    re_path(r'^$', LandingView.as_view(), name='landing'),
    re_path(r'^login/?$', LoginView.as_view(), name='login'),
    re_path(r'^signup/?$', SignupView.as_view(), name='signup'),
    re_path(r'^logout/?$', auth_views.LogoutView.as_view(
        next_page='/nosystemd/login?logged_out=true'), name='logout'),
    re_path(r'reset-password/?$', PasswordResetView.as_view(), name='reset_password'),
    re_path(r'reset-password-confirm/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/$',
        PasswordResetConfirmView.as_view(), name='reset_password_confirm'),
    re_path(r'^donations/?$', DonationListView.as_view(), name='donations'),
    re_path(r'donations/(?P<pk>\d+)/?$', DonationDetailView.as_view(), name='donations'),
    re_path(r'^make_donation/?$', DonationView.as_view(), name='make_donation'),
    re_path(r'donations/status/?$', DonatorStatusDetailView.as_view(),
        name='donator_status'),
    re_path(r'donations/status/(?P<pk>\d+)/?$', ChangeDonatorStatusDetailView.as_view(),
        name='change_donator_status'),
    # re_path(r'^donation/invoice?$', DonationView.as_view(), name='donation_detail'),

]
