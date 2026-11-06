"""Маршруты интерфейса MVP."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="web/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("connect/", views.connect, name="connect"),
    path("sources/", views.source_view, name="sources"),
    path("sources/parse/", views.parse_source, name="parse_source"),
    path("ads/", views.ads, name="ads"),
    path("ads/<int:ad_id>/", views.ad_detail, name="ad_detail"),
    path("ads/<int:ad_id>/prepare/", views.prepare_ad, name="prepare_ad"),
    path("ads/<int:ad_id>/publish/", views.publish_ad, name="publish_ad"),
    path("publications/", views.publications, name="publications"),
    path("settings/", views.settings_view, name="settings"),
    path("jobs/", views.jobs, name="jobs"),
    path("jobs/<int:job_id>/", views.job_detail, name="job_detail"),
    path("api/jobs/<int:job_id>/", views.job_status, name="job_status"),
    path("photos/<int:photo_id>/", views.photo, name="photo"),
]
