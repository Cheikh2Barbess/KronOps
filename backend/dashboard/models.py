from django.db import models

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
