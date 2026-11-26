from django.urls import path

from tenants.api import views

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("sites/", views.SiteListView.as_view(), name="site-list"),
    path("sites/<uuid:pk>/", views.SiteDetailView.as_view(), name="site-detail"),
]
