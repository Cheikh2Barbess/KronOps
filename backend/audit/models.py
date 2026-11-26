from django.conf import settings
from django.db import models

from core.models import UUIDModel


class AuditLog(UUIDModel):
    """Journal d'audit. INSERTION SEULE, imposee par PostgreSQL (trigger + REVOKE).

    Ne jamais appeler update(), delete() ou save() sur une ligne existante : la base refusera.
    Une correction = une nouvelle ligne.
    """

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    action = models.CharField(max_length=50)  # ex. "create", "update", "block"
    entity_type = models.CharField(max_length=100)  # ex. "tenants.site"
    entity_id = models.UUIDField()
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "entrée d'audit"
        indexes = [
            models.Index(fields=["tenant", "entity_type", "entity_id"]),
            models.Index(fields=["tenant", "created_at"]),
        ]
