"""Lectures du journal d'audit. Pas de filtre tenant ici : la RLS de PostgreSQL le fait."""

from audit.models import AuditLog


def audit_entries(*, entity_type=None, entity_id=None, action=None, user_id=None, date_from=None, date_to=None):
    qs = AuditLog.objects.select_related("user").order_by("-created_at", "-id")
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if entity_id:
        qs = qs.filter(entity_id=entity_id)
    if action:
        qs = qs.filter(action=action)
    if user_id:
        qs = qs.filter(user_id=user_id)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs
