from django.urls import path

from audit.api import views

urlpatterns = [
    path("audit/", views.AuditListView.as_view(), name="audit-list"),
    path("audit/users/", views.AuditUserListView.as_view(), name="audit-users"),
]
