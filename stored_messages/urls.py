"""
At the moment this module does something only when restframework is available
"""
from django.conf import settings

if 'rest_framework' in settings.INSTALLED_APPS:
    from rest_framework.routers import DefaultRouter
    from django.urls import re_path, include
    from . import views

    router = DefaultRouter()
    router.register(r'inbox', views.InboxViewSet, base_name='inbox')

    urlpatterns = [
        re_path(r'^', include(router.urls)),
        re_path(r'^mark_all_read/$', views.mark_all_read, name='mark_all_read'),
    ]
