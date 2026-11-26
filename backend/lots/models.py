from django.conf import settings
from django.db import models
from django.db.models import F, Q

from core.models import TenantModel


class Lot(TenantModel):
    """Lot de matiere, d'emballage ou de produit. Jamais supprime.

    Le stock d'un lot n'est PAS stocke ici : c'est la somme de ses mouvements (voir selectors.py).
    L'etat « epuise » (solde = 0) et « perime » (DLC depassee) sont calcules, pas stockes.
    """

    class Status(models.TextChoices):
        DISPONIBLE = "disponible", "Disponible"
        BLOQUE = "bloque", "Bloqué"
        DETRUIT = "detruit", "Détruit"

    class DateType(models.TextChoices):
        DLC = "dlc", "DLC (à consommer jusqu'au)"
        DDM = "ddm", "DDM (à consommer de préférence avant)"

    article = models.ForeignKey("catalog.Article", on_delete=models.PROTECT, related_name="lots")
    code = models.CharField("code interne", max_length=80)
    supplier = models.ForeignKey(
        "catalog.Partner", on_delete=models.PROTECT, null=True, blank=True, related_name="supplied_lots"
    )
    supplier_lot_code = models.CharField("n° de lot fournisseur", max_length=100, blank=True)
    date_type = models.CharField("type de date", max_length=3, choices=DateType.choices, blank=True)
    expiry_date = models.DateField("DLC ou DDM", null=True, blank=True)
    production_date = models.DateField("date d'entrée ou de fabrication")
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.DISPONIBLE)
    block_code = models.CharField("code du motif de blocage", max_length=40, blank=True)
    block_reason = models.TextField("motif de blocage (libellé et précision)", blank=True)
    reception_temperature_c = models.DecimalField(
        "température à réception (°C)", max_digits=5, decimal_places=1, null=True, blank=True
    )
    reception_visual_ok = models.BooleanField("conformité visuelle", null=True, blank=True)

    class Meta:
        verbose_name = "lot"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="lot_unique_code_per_tenant"),
            models.CheckConstraint(
                condition=Q(expiry_date__isnull=True) | ~Q(date_type=""), name="lot_expiry_has_date_type"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "article", "status"]),
            models.Index(fields=["tenant", "supplier_lot_code"]),
        ]

    def __str__(self):
        return self.code


class Movement(TenantModel):
    """Mouvement de stock. INSERTION SEULE (trigger + REVOKE) : une correction est un contre-mouvement.

    `quantity` est signee, dans l'unite de base de l'article : positive en entree, negative en sortie.
    """

    class Type(models.TextChoices):
        RECEPTION = "reception", "Réception"
        PRODUCTION = "production", "Production"
        CONSOMMATION = "consommation", "Consommation"
        EXPEDITION = "expedition", "Expédition"
        AJUSTEMENT = "ajustement", "Ajustement d'inventaire"
        REBUT = "rebut", "Rebut ou perte"
        DESTRUCTION = "destruction", "Destruction"
        RETOUR = "retour", "Retour client"
        ANNULATION = "annulation", "Annulation"

    ENTRY_TYPES = {Type.RECEPTION, Type.PRODUCTION, Type.RETOUR}
    EXIT_TYPES = {Type.CONSOMMATION, Type.EXPEDITION, Type.REBUT, Type.DESTRUCTION}

    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField("type", max_length=20, choices=Type.choices)
    quantity = models.DecimalField("quantité (unité de base, signée)", max_digits=18, decimal_places=3)
    partner = models.ForeignKey("catalog.Partner", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    reason = models.TextField("motif", blank=True)
    occurred_at = models.DateTimeField("date réelle déclarée")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")

    class Meta:
        verbose_name = "mouvement"
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name="movement_quantity_not_zero"),
            models.CheckConstraint(
                condition=~Q(movement_type="annulation") | Q(reverses__isnull=False),
                name="movement_reversal_has_origin",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "lot", "occurred_at"]),
            models.Index(fields=["tenant", "movement_type"]),
        ]


class LotLink(TenantModel):
    """Genealogie : le lot parent entre dans la composition du lot enfant. INSERTION SEULE.

    Ecrite par la declaration de production (US-08). Base des recherches amont et aval.
    """

    parent_lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="child_links")
    child_lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="parent_links")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")

    class Meta:
        verbose_name = "lien de généalogie"
        constraints = [
            models.CheckConstraint(condition=~Q(parent_lot=F("child_lot")), name="lotlink_not_self"),
        ]
        indexes = [
            models.Index(fields=["tenant", "parent_lot"]),
            models.Index(fields=["tenant", "child_lot"]),
        ]


class ApprovalRequest(TenantModel):
    """US-20 Double validation : demande d'une action sensible, executee seulement apres la validation
    d'un 2e utilisateur d'un autre role. Jamais supprimee : son statut evolue, chaque etape est auditee."""

    class Action(models.TextChoices):
        RELEASE = "release", "Débloquer le lot"
        DESTROY = "destroy", "Détruire le lot"
        SCRAP = "scrap", "Rebut ou perte"
        ADJUST = "adjust", "Ajustement de stock"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        APPROVED = "approved", "Validée"
        REJECTED = "rejected", "Refusée"
        CANCELLED = "cancelled", "Annulée"

    action = models.CharField("action", max_length=20, choices=Action.choices)
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="approval_requests")
    quantity = models.DecimalField(
        "quantité (unité de base, signée pour un ajustement)", max_digits=18, decimal_places=3, null=True, blank=True
    )
    reason_code = models.CharField("motif (code)", max_length=40)
    comment = models.TextField("précision", blank=True)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_role = models.CharField("rôle du demandeur", max_length=20)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_role = models.CharField("rôle du validateur", max_length=20, blank=True)
    decided_at = models.DateTimeField("date de décision", null=True, blank=True)
    decision_code = models.CharField("motif du refus (code)", max_length=40, blank=True)
    decision_comment = models.TextField("précision du refus", blank=True)
    movement = models.OneToOneField(
        Movement, on_delete=models.PROTECT, null=True, blank=True, related_name="approval",
        help_text="Mouvement cree par la validation (rebut, ajustement, destruction).",
    )

    class Meta:
        verbose_name = "demande de double validation"
        constraints = [
            # Garde-fou en base : le validateur n'est jamais le demandeur.
            models.CheckConstraint(
                condition=Q(decided_by__isnull=True) | ~Q(decided_by=F("requested_by")) | Q(status="cancelled"),
                name="approval_not_self_decided",
            ),
            models.CheckConstraint(
                condition=Q(action__in=["release", "destroy"]) | Q(quantity__isnull=False),
                name="approval_quantity_required",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status", "created_at"])]
