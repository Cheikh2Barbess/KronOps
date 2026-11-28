from django.urls import path

from dashboard.api import views

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/targets/", views.TargetView.as_view(), name="dashboard-targets"),
    path("dashboard/gap/", views.GapView.as_view(), name="dashboard-gap"),
    path("dashboard/gap/<uuid:article_id>/", views.GapProductView.as_view(), name="dashboard-gap-product"),
    path("dashboard/gap/<uuid:article_id>/equipment/<uuid:equipment_id>/", views.GapEquipmentView.as_view(),
         name="dashboard-gap-equipment"),
    path("dashboard/thresholds/", views.ThresholdListView.as_view(), name="dashboard-thresholds"),
    path("dashboard/thresholds/<str:code>/", views.ThresholdDetailView.as_view(), name="dashboard-threshold"),
]
