__author__ = 'tomislav'
from django.urls import re_path
from django.contrib.auth.decorators import login_required

from . import views

urlpatterns = (
    re_path(r"^$", views.LoginRegistrationView.as_view(), name='login_glarus'),
    re_path(r"^validate/(?P<validate_slug>.*)/$", views.validate_email),
    re_path(r"^membership/$", login_required(views.MembershipView.as_view()), name='membership'),
    re_path(r'logout/?$', views.logout_glarus, name='logout_glarus'),
    re_path(r"^buy/(?P<time>\w+)/$", login_required(views.CreditCardView.as_view()), name='payment'),
    re_path(r'^buy/(?P<time>\w+)/reset', login_required(views.reset), name='reset')
)
