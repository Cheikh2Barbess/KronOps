from django.urls import path

from production.api import views

urlpatterns = [
    path("equipment/", views.EquipmentListView.as_view(), name="equipment-list"),
    path("equipment/<uuid:pk>/", views.EquipmentDetailView.as_view(), name="equipment-detail"),
    path("production/runs/", views.RunListView.as_view(), name="run-list"),
    path("production/runs/options/", views.ProductionOptionsView.as_view(), name="run-options"),
    path("production/runs/<uuid:pk>/", views.RunDetailView.as_view(), name="run-detail"),
    path("production/runs/<uuid:pk>/cancel/", views.RunCancelView.as_view(), name="run-cancel"),
    path("production/steps/", views.StepSettingsView.as_view(), name="step-settings"),
    path("production/routes/", views.RouteListView.as_view(), name="route-list"),
    path("production/routes/<uuid:pk>/", views.RouteDetailView.as_view(), name="route-detail"),
    path("production/pipeline/", views.PipelineView.as_view(), name="pipeline"),
    path("production/stops/", views.StopListView.as_view(), name="stop-list"),
    path("production/stops/options/", views.StopOptionsView.as_view(), name="stop-options"),
    path("production/stops/<uuid:pk>/end/", views.StopEndView.as_view(), name="stop-end"),
    path("production/stops/<uuid:pk>/cancel/", views.StopCancelView.as_view(), name="stop-cancel"),
    path("production/balance/", views.MaterialBalanceView.as_view(), name="material-balance"),
]
