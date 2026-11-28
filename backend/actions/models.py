from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import TenantModel


class Action(TenantModel):
    """Action corrective ou demande d'intervention : qui fait quoi, pour quand, sur quel arret, lot ou produit.

    Objet choisi dans une liste fermee (actions.reasons). Rien n'est efface : une action se termine avec un
    resultat code, ou s'annule avec un motif.
    """

    class Status(models.TextChoices):
        OUVERTE = "ouverte", "Ouverte"
        EN_COURS = "en_cours", "En cours"
        TERMINEE = "terminee", "Terminée"
        ANNULEE = "annulee", "Annulée"

    action_type = models.CharField("type", max_length=20)
    subject_code = models.CharField("objet (code)", max_length=40)
    comment = models.TextField("précision", blank=True)
    priority = models.CharField("priorité", max_length=10, default="normale")
    origin = models.CharField("origine", max_length=20, default="saisie")
    status = models.CharField("statut", max_length=10, choices=Status.choices, default=Status.OUVERTE)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="+", verbose_name="responsable")
    due_date = models.DateField("échéance")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    # Ce que l'action concerne (un ou plusieurs liens, tous facultatifs).
    line_stop = models.ForeignKey("production.LineStop", on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="actions")
    equipment = models.ForeignKey("production.Equipment", on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="+")
    lot = models.ForeignKey("lots.Lot", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    article = models.ForeignKey("catalog.Article", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    started_at = models.DateTimeField("commencée le", null=True, blank=True)
    closed_at = models.DateTimeField("terminée le", null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="+")
    result_code = models.CharField("résultat (code)", max_length=20, blank=True)
    result_comment = models.TextField("précision sur le résultat", blank=True)
    cancelled_at = models.DateTimeField("annulée le", null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="+")
    cancel_reason_code = models.CharField("motif d'annulation (code)", max_length=40, blank=True)
    cancel_comment = models.TextField("précision sur l'annulation", blank=True)

    class Meta:
        verbose_name = "action"
        constraints = [
            models.CheckConstraint(condition=~Q(status="terminee") | Q(closed_at__isnull=False),
                                   name="action_closed_has_date"),
        ]
        indexes = [models.Index(fields=["tenant", "status", "due_date"])]
