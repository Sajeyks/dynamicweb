from django.urls import re_path

from .views import IndexView, LoginView, ContactView


app_name = 'alplora'

urlpatterns = [
    re_path(r'^$', IndexView.as_view(), name='index'),
    re_path(r'login/', LoginView.as_view(), name='login'),
    re_path(r'contact', ContactView.as_view(), name='contact'),
    #     re_path(r'^/beta-program/?$', BetaProgramView.as_view(), name='beta'),
    #     re_path(r'^/landing/?$', LandingProgramView.as_view(), name='landing'),
]
