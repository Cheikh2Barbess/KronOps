from django.db import models

from core.models import UUIDModel


class OutboxEvent(UUIDModel):
    """Evenement metier, ecrit dans la MEME transaction que l'action (patron outbox).

    Phase 1 : personne ne lit cette table, elle se remplit.
    Phase 2 : une tache Celery traite les lignes ou processed_at est vide.
    """

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="+")
    event_type = models.CharField(max_length=100)  # ex. "lot.consumed"
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "événement"
        indexes = [models.Index(fields=["processed_at", "created_at"])]
