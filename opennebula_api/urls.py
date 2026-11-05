from django.urls import re_path
from rest_framework.urlpatterns import format_suffix_patterns
from .views import VmCreateView, VmDetailsView

app_name = 'opennebula_api'

urlpatterns = {
    re_path(r'^vms/$', VmCreateView.as_view(), name="vm_create"),
    re_path(r'^vms/(?P<pk>[0-9]+)/$', VmDetailsView.as_view(),
        name="vm_details"),
}

urlpatterns = format_suffix_patterns(urlpatterns)
