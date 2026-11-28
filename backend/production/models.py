"""Declarations d'etapes de production : murissement, tri, sechage, conditionnement, palettisation.

Une declaration consomme un ou plusieurs lots (en tout ou en partie) et cree UN lot produit.
Un lot reparti sur plusieurs sechoirs = plusieurs declarations qui consomment chacune une partie du lot.
Tables en INSERTION SEULE : une erreur se corrige par un contre-mouvement, jamais en modifiant la ligne.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from core.models import TenantModel


class Equipment(TenantModel):
    """Equipement ou zone ou se deroule une etape (sechoir, chambre de murissement, ligne...)."""

    class Type(models.TextChoices):
        SECHOIR = "sechoir", "Séchoir ou four"
        MURISSEMENT = "murissement", "Chambre ou aire de mûrissement"
        TRI = "tri", "Table ou ligne de tri"
        PREPARATION = "preparation", "Ligne de préparation (lavage, épluchage, découpe)"
        CONDITIONNEMENT = "conditionnement", "Ligne de conditionnement"
        AUTRE = "autre", "Autre"

    code = models.CharField(max_length=30)
    name = models.CharField("nom", max_length=100)
    equipment_type = models.CharField("type", max_length=20, choices=Type.choices)
    site = models.ForeignKey("tenants.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "équipement"
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="equipment_unique_code_per_tenant")]

    def __str__(self):
        return f"{self.code} {self.name}"


class ProductionRun(TenantModel):
    """Une etape declaree. INSERTION SEULE."""

    class Step(models.TextChoices):
        # Catalogue complet, dans l'ordre habituel du procede (etude COLEAD sur la mangue sechee, plus la coco).
        # Chaque entreprise active, desactive et ordonne ses etapes (StepSetting). Sans reglage, seules les six
        # etapes historiques sont actives. Ne jamais retirer un code : des declarations l'utilisent.
        MURISSEMENT = "murissement", "Mûrissement"
        LAVAGE = "lavage", "Lavage"
        TRI = "tri", "Tri"
        PREPARATION = "preparation", "Préparation (lavage, épluchage, découpe)"
        CASSAGE = "cassage", "Cassage et écalage (coco)"
        PARAGE = "parage", "Parage et dépelliculage (coco)"
        EPLUCHAGE_DECOUPE = "epluchage_decoupe", "Épluchage et découpe"
        RAPAGE = "rapage", "Râpage ou découpe de la chair (coco)"
        PRETRAITEMENT = "pretraitement", "Prétraitement (trempage, blanchiment)"
        PASTEURISATION = "pasteurisation", "Pasteurisation"
        SECHAGE = "sechage", "Séchage"
        REFROIDISSEMENT = "refroidissement", "Refroidissement et homogénéisation"
        TRI_FINITION = "tri_finition", "Tri et finition"
        CONDITIONNEMENT = "conditionnement", "Conditionnement (cartons, sachets)"
        PALETTISATION = "palettisation", "Palettisation"

    step = models.CharField("étape", max_length=20, choices=Step.choices)
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, null=True, blank=True, related_name="runs")
    site = models.ForeignKey("tenants.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    output_lot = models.OneToOneField("lots.Lot", on_delete=models.PROTECT, related_name="production_run")
    # Quantites en unite de base. `input_quantity` = matiere comptee dans le bilan (meme unite que le produit,
    # hors emballages). Figees a la declaration, comme la fourchette de rendement de reference.
    input_quantity = models.DecimalField("matière consommée", max_digits=18, decimal_places=3)
    output_quantity = models.DecimalField("quantité produite", max_digits=18, decimal_places=3)
    waste_quantity = models.DecimalField("déchets déclarés", max_digits=18, decimal_places=3, default=0)
    waste_code = models.CharField("nature des déchets (code)", max_length=40, blank=True)
    waste_comment = models.TextField("précision sur les déchets", blank=True)
    yield_min_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    yield_max_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    started_at = models.DateTimeField("début")
    ended_at = models.DateTimeField("fin")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    late_reason_code = models.CharField("motif de saisie tardive (code)", max_length=40, blank=True)
    late_comment = models.TextField("précision sur la saisie tardive", blank=True)

    class Meta:
        verbose_name = "déclaration de production"
        constraints = [
            models.CheckConstraint(condition=Q(output_quantity__gt=0), name="run_output_positive"),
            models.CheckConstraint(condition=Q(waste_quantity__gte=0), name="run_waste_not_negative"),
            models.CheckConstraint(condition=Q(ended_at__gte=models.F("started_at")), name="run_end_after_start"),
        ]
        indexes = [models.Index(fields=["tenant", "ended_at"]), models.Index(fields=["tenant", "step", "ended_at"])]


class ProductionInput(TenantModel):
    """Lot consomme par une declaration, avec la quantite prise (une partie du lot ou tout le lot). INSERTION SEULE."""

    run = models.ForeignKey(ProductionRun, on_delete=models.PROTECT, related_name="inputs")
    lot = models.ForeignKey("lots.Lot", on_delete=models.PROTECT, related_name="production_uses")
    quantity = models.DecimalField("quantité consommée (unité de base)", max_digits=18, decimal_places=3)
    movement = models.OneToOneField("lots.Movement", on_delete=models.PROTECT, related_name="production_input")

    class Meta:
        verbose_name = "lot consommé"
        constraints = [
            models.UniqueConstraint(fields=["run", "lot"], name="run_input_unique_lot"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="run_input_positive"),
        ]


class RunCancellation(TenantModel):
    """Annulation d'une declaration. INSERTION SEULE : la declaration reste visible, marquee annulee.

    Les consommations et la production sont defaites par des contre-mouvements (annulation), le lot produit
    est bloque avec le motif « déclaration annulée ».
    """

    run = models.OneToOneField(ProductionRun, on_delete=models.PROTECT, related_name="cancellation")
    reason_code = models.CharField("motif (code)", max_length=40)
    comment = models.TextField("précision", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")

    class Meta:
        verbose_name = "annulation de déclaration"


DEFAULT_ACTIVE_STEPS = (
    ProductionRun.Step.MURISSEMENT, ProductionRun.Step.TRI, ProductionRun.Step.PREPARATION,
    ProductionRun.Step.SECHAGE, ProductionRun.Step.CONDITIONNEMENT, ProductionRun.Step.PALETTISATION,
)


class StepSetting(TenantModel):
    """Reglage d'une etape du catalogue pour une entreprise : active ou non, et sa place dans la liste.

    Une etape sans ligne garde son reglage par defaut (DEFAULT_ACTIVE_STEPS, ordre du catalogue).
    Desactiver une etape ne touche pas aux declarations deja faites.
    """

    step = models.CharField("étape", max_length=20, choices=ProductionRun.Step.choices)
    is_active = models.BooleanField("active", default=True)
    position = models.PositiveSmallIntegerField("ordre")

    class Meta:
        verbose_name = "réglage d'étape"
        constraints = [models.UniqueConstraint(fields=["tenant", "step"], name="stepsetting_unique_step_per_tenant")]

    def __str__(self):
        return self.step


class ProductRoute(TenantModel):
    """Parcours d'un produit : les etapes permises pour ses articles (la mangue et la coco n'ont pas les memes).

    Un article sans parcours, ou dans un parcours desactive, suit les etapes actives de l'entreprise.
    On ne supprime pas un parcours : on le desactive.
    """

    name = models.CharField("nom", max_length=100)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "parcours de produit"
        constraints = [
            models.UniqueConstraint("tenant", Lower("name"), name="productroute_unique_name_per_tenant"),
        ]

    def __str__(self):
        return self.name


class RouteStep(TenantModel):
    """Etape permise dans un parcours, a sa place dans l'ordre propre au parcours (la coco casse avant de laver)."""

    route = models.ForeignKey(ProductRoute, on_delete=models.CASCADE, related_name="steps")
    step = models.CharField("étape", max_length=20, choices=ProductionRun.Step.choices)
    # 0 pour les lignes creees avant l'ordre par parcours : elles suivent alors l'ordre de l'entreprise.
    position = models.PositiveSmallIntegerField("ordre", default=0)

    class Meta:
        verbose_name = "étape d'un parcours"
        constraints = [models.UniqueConstraint(fields=["route", "step"], name="routestep_unique_step_per_route")]


class RouteArticle(TenantModel):
    """Article rattache a un parcours. Un article appartient a un seul parcours."""

    route = models.ForeignKey(ProductRoute, on_delete=models.CASCADE, related_name="articles")
    article = models.ForeignKey("catalog.Article", on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "article d'un parcours"
        constraints = [models.UniqueConstraint(fields=["tenant", "article"], name="routearticle_unique_article")]


class PipelineSetting(TenantModel):
    """Activation d'un module facultatif du pipeline (voir production/pipeline.py). Actif sans ligne."""

    code = models.CharField("code", max_length=40)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "réglage du pipeline"
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="pipelinesetting_unique_code")]

    def __str__(self):
        return self.code


class LineStop(TenantModel):
    """Arret d'un equipement (sechoir, ligne...), declare au poste. Cause choisie dans production.reasons.

    Un arret sans fin est « en cours ». Pas d'effacement : une erreur s'annule avec un motif (la ligne reste).
    """

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="stops")
    site = models.ForeignKey("tenants.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    started_at = models.DateTimeField("début")
    ended_at = models.DateTimeField("fin", null=True, blank=True)
    cause_code = models.CharField("cause (code)", max_length=40)
    comment = models.TextField("précision", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    ended_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="+")
    cancelled_at = models.DateTimeField("annulé le", null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="+")
    cancel_reason_code = models.CharField("motif d'annulation (code)", max_length=40, blank=True)
    cancel_comment = models.TextField("précision sur l'annulation", blank=True)

    class Meta:
        verbose_name = "arrêt de ligne"
        constraints = [
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("started_at")),
                                   name="linestop_end_after_start"),
        ]
        indexes = [models.Index(fields=["tenant", "started_at"]), models.Index(fields=["tenant", "equipment"])]
