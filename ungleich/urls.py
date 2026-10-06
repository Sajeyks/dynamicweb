from django.urls import re_path
from . import views
from .views import PostDetailViewUngleich

app_name = 'ungleich'

urlpatterns = [
    re_path(r'^$', views.PostListViewUngleich.as_view(), name="post-list"),
    # re_path(r'^$',views.PostListView.as_view()),
    re_path(r'^(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<slug>\w[-\w]*)/$',
        PostDetailViewUngleich.as_view(), name="post-detail")
]
