from django.urls import path

from actions.api import views

urlpatterns = [
    path("actions/", views.ActionListView.as_view(), name="actions"),
    path("actions/options/", views.ActionOptionsView.as_view(), name="action-options"),
    path("actions/alerts/", views.ActionAlertsView.as_view(), name="action-alerts"),
    path("actions/call/", views.ActionCallView.as_view(), name="action-call"),
    path("actions/<uuid:action_id>/", views.ActionDetailView.as_view(), name="action-detail"),
    path("actions/<uuid:action_id>/assign/", views.ActionAssignView.as_view(), name="action-assign"),
    path("actions/<uuid:action_id>/start/", views.ActionStartView.as_view(), name="action-start"),
    path("actions/<uuid:action_id>/close/", views.ActionCloseView.as_view(), name="action-close"),
    path("actions/<uuid:action_id>/cancel/", views.ActionCancelView.as_view(), name="action-cancel"),
]
