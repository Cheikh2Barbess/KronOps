from django.urls import path

from lots.api import views

urlpatterns = [
    path("lots/", views.LotListView.as_view(), name="lot-list"),
    path("lots/receptions/", views.ReceptionView.as_view(), name="lot-reception"),
    path("lots/receptions/options/", views.ReceptionOptionsView.as_view(), name="lot-reception-options"),
    path("lots/transfers/", views.TransferListView.as_view(), name="lot-transfer-list"),
    path("lots/transfers/options/", views.TransferOptionsView.as_view(), name="lot-transfer-options"),
    path("lots/<uuid:pk>/", views.LotDetailView.as_view(), name="lot-detail"),
    path("lots/<uuid:pk>/block/", views.BlockLotView.as_view(), name="lot-block"),
    path("movements/<uuid:pk>/reverse/", views.ReverseMovementView.as_view(), name="movement-reverse"),
    path("approvals/", views.ApprovalListView.as_view(), name="approval-list"),
    path("approvals/reasons/", views.ApprovalReasonsView.as_view(), name="approval-reasons"),
    path("approvals/<uuid:pk>/", views.ApprovalDetailView.as_view(), name="approval-detail"),
    path("approvals/<uuid:pk>/approve/", views.ApproveView.as_view(), name="approval-approve"),
    path("approvals/<uuid:pk>/reject/", views.RejectView.as_view(), name="approval-reject"),
    path("approvals/<uuid:pk>/cancel/", views.CancelView.as_view(), name="approval-cancel"),
    path("traceability/downstream/", views.DownstreamView.as_view(), name="trace-downstream"),
    path("traceability/upstream/", views.UpstreamView.as_view(), name="trace-upstream"),
    path("traceability/recall/", views.RecallView.as_view(), name="trace-recall"),
    path("lots/quality-checks/options/", views.QualityOptionsView.as_view(), name="quality-options"),
    path("lots/<uuid:pk>/quality-checks/", views.QualityCheckView.as_view(), name="lot-quality-check"),
]
