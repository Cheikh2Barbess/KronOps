from django.urls import path

from dashboard.api import views

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/thresholds/", views.ThresholdListView.as_view(), name="dashboard-thresholds"),
    path("dashboard/thresholds/<str:code>/", views.ThresholdDetailView.as_view(), name="dashboard-threshold"),
]
