"""Expeditions : un depart vers un client (souvent un conteneur), avec ses lots et ses documents d'export.

Tables en INSERTION SEULE. Chaque ligne cree un mouvement « expedition » sur le lot. Une erreur se corrige
par l'annulation du mouvement (contre-mouvement), jamais en modifiant la ligne.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import TenantModel


class Shipment(TenantModel):
    customer = models.ForeignKey("catalog.Partner", on_delete=models.PROTECT, related_name="shipments")
    site = models.ForeignKey("tenants.Site", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    shipped_at = models.DateTimeField("date de départ")
    container_number = models.CharField("n° de conteneur", max_length=20, blank=True)
    seal_number = models.CharField("n° de plomb (scellé)", max_length=40, blank=True)
    # Certificat d'inspection TRACES (COI) exige pour un produit bio importe dans l'UE (reglement (UE) 2021/2306).
    export_document_ref = models.CharField("n° du certificat d'inspection (COI TRACES)", max_length=60, blank=True)
    bill_of_lading = models.CharField("n° de connaissement (BL)", max_length=60, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    late_reason_code = models.CharField("motif de saisie tardive (code)", max_length=40, blank=True)
    late_comment = models.TextField("précision sur la saisie tardive", blank=True)

    class Meta:
        verbose_name = "expédition"
        indexes = [
            models.Index(fields=["tenant", "shipped_at"]),
            models.Index(fields=["tenant", "container_number"]),
        ]


class ShipmentLine(TenantModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="lines")
    lot = models.ForeignKey("lots.Lot", on_delete=models.PROTECT, related_name="shipment_lines")
    quantity = models.DecimalField("quantité (unité de base)", max_digits=18, decimal_places=3)
    movement = models.OneToOneField("lots.Movement", on_delete=models.PROTECT, related_name="shipment_line")

    class Meta:
        verbose_name = "ligne d'expédition"
        constraints = [
            models.UniqueConstraint(fields=["shipment", "lot"], name="shipment_line_unique_lot"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="shipment_line_positive"),
        ]
