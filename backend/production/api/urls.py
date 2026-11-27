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
    path("production/balance/", views.MaterialBalanceView.as_view(), name="material-balance"),
]
