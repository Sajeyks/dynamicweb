from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import views as auth_views

from . import views
from .views import ContactView, IndexView, HistoryView, LoginView, SignupView,\
    PasswordResetView, PasswordResetConfirmView, MembershipPaymentView, MembershipActivatedView,\
    MembershipPricingView, BookingSelectDatesView, BookingPaymentView, OrdersBookingDetailView,\
    BookingOrdersListView, MembershipOrdersListView, OrdersMembershipDetailView, \
    MembershipDeactivateView, MembershipDeactivateSuccessView, UserBillingAddressView, EditCreditCardView, \
    MembershipReactivateView, SupportusView


# from membership.views import LoginRegistrationView

app_name = 'digitalglarus'

urlpatterns = [
    re_path(_(r'booking/payment/edit/?$'),
        EditCreditCardView.as_view(), name='edit_credit_card'),
    re_path(_(r'^$'), IndexView.as_view(), name='landing'),
    # re_path(_(r'new_credit_card/?$'), TermsAndConditions, name='TermsAndConditions'),
    re_path(_(r'support-us/?$'), SupportusView.as_view(), name='supportus'),
    re_path(_(r'contact/?$'), ContactView.as_view(), name='contact'),
    re_path(_(r'login/?$'), LoginView.as_view(), name='login'),
    re_path(_(r'signup/?$'), SignupView.as_view(), name='signup'),
    re_path(r'^logout/?$', auth_views.LogoutView.as_view(
        next_page='/digitalglarus/login?logged_out=true'), name='logout'),
    re_path(r'reset-password/?$', PasswordResetView.as_view(), name='reset_password'),
    re_path(r'reset-password-confirm/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/$',
        PasswordResetConfirmView.as_view(), name='reset_password_confirm'),
    re_path(_(r'history/?$'), HistoryView.as_view(), name='history'),
    re_path(_(r'users/billing_address/?$'), UserBillingAddressView.as_view(),
        name='user_billing_address'),
    re_path(_(r'booking/?$'), BookingSelectDatesView.as_view(), name='booking'),
    re_path(_(r'booking/payment/?$'),
        BookingPaymentView.as_view(), name='booking_payment'),
    re_path(_(r'booking/orders/(?P<pk>\d+)/?$'), OrdersBookingDetailView.as_view(),
        name='booking_orders_detail'),
    # re_path(_(r'booking/orders/(?P<pk>\d+)/cancel/?$'), BookingCancelView.as_view(),
    #     name='booking_orders_cancel'),
    re_path(_(r'booking/orders/?$'), BookingOrdersListView.as_view(),
        name='booking_orders_list'),
    re_path(_(r'membership/payment/?$'),
        MembershipPaymentView.as_view(), name='membership_payment'),
    re_path(_(r'membership/activated/?$'), MembershipActivatedView.as_view(),
        name='membership_activated'),
    re_path(_(r'membership/deactivate/?$'), MembershipDeactivateView.as_view(),
        name='membership_deactivate'),
    re_path(_(r'membership/reactivate/?$'), MembershipReactivateView.as_view(),
        name='membership_reactivate'),
    re_path(_(r'membership/deactivate/success/?$'), MembershipDeactivateSuccessView.as_view(),
        name='membership_deactivate_success'),
    re_path(_(r'membership/pricing/?$'), MembershipPricingView.as_view(),
        name='membership_pricing'),
    re_path(_(r'membership/orders/(?P<pk>\d+)/?$'), OrdersMembershipDetailView.as_view(),
        name='membership_orders_detail'),
    re_path(_(r'membership/orders/?$'), MembershipOrdersListView.as_view(),
        name='membership_orders_list'),
    re_path(_(r'supporters/?$'), views.supporters, name='supporters'),
    re_path(_(r'support-us/?$'), views.support, name='support'),
    re_path(r'^blog/(?P<slug>\w[-\w]*)/$', views.blog_detail, name='blog-detail'),
    re_path(r'blog/$', views.blog, name='blog'),
]
