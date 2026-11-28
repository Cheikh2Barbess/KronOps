from django.db import models
from django.db.models import Q

from core.models import TenantModel
from dashboard.indicators import THRESHOLDS


class DashboardThreshold(TenantModel):
    """Seuil d'un indicateur choisi par l'entreprise. Sans ligne : la valeur par defaut s'applique."""

    code = models.CharField("indicateur", max_length=40, choices=[(c, v["label"]) for c, v in THRESHOLDS.items()])
    green = models.DecimalField("seuil vert", max_digits=12, decimal_places=2)
    red = models.DecimalField("seuil rouge", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "seuil du tableau de bord"
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="dashboardthreshold_unique_code")]

    def __str__(self):
        return self.code


class ProductionTarget(TenantModel):
    """Cible de production d'un article pour un mois (Sollwert), en unite de base. Saisie par l'Admin.

    Le reel (Istwert) vient des declarations d'etape qui produisent cet article, hors declarations annulees.
    """

    article = models.ForeignKey("catalog.Article", on_delete=models.PROTECT, related_name="+")
    month = models.DateField("mois (premier jour)")
    quantity = models.DecimalField("cible", max_digits=18, decimal_places=3)

    class Meta:
        verbose_name = "cible de production"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "article", "month"], name="productiontarget_unique_month"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="productiontarget_positive"),
        ]
