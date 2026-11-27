from django.urls import path

from shipping.api import views

urlpatterns = [
    path("shipments/", views.ShipmentListView.as_view(), name="shipment-list"),
    path("shipments/options/", views.ShipmentOptionsView.as_view(), name="shipment-options"),
    path("shipments/<uuid:pk>/", views.ShipmentDetailView.as_view(), name="shipment-detail"),
]
