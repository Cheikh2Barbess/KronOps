from django.urls import path

from lots.api import views

urlpatterns = [
    path("lots/", views.LotListView.as_view(), name="lot-list"),
    path("lots/receptions/", views.ReceptionView.as_view(), name="lot-reception"),
    path("lots/<uuid:pk>/", views.LotDetailView.as_view(), name="lot-detail"),
    path("lots/<uuid:pk>/block/", views.BlockLotView.as_view(), name="lot-block"),
    path("movements/<uuid:pk>/reverse/", views.ReverseMovementView.as_view(), name="movement-reverse"),
    path("traceability/downstream/", views.DownstreamView.as_view(), name="trace-downstream"),
    path("traceability/upstream/", views.UpstreamView.as_view(), name="trace-upstream"),
]
