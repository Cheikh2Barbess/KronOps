"""Regles metier des expeditions. Toute ecriture passe par ici."""

import re

from django.db import transaction
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from events.services import publish_event
from lots import services as lots
from lots.models import Movement
from shipping.models import Shipment, ShipmentLine

# Format ISO 6346 : 3 lettres du proprietaire, 1 lettre de categorie, 6 chiffres et 1 chiffre de controle.
# Le chiffre de controle n'est pas verifie ici (format seulement).
CONTAINER_RE = re.compile(r"^[A-Z]{4}\d{7}$")


def normalize_container(number):
    return re.sub(r"[\s-]", "", number or "").upper()


def _values(shipment):
    return {
        "customer_id": str(shipment.customer_id), "site_id": str(shipment.site_id) if shipment.site_id else None,
        "shipped_at": shipment.shipped_at.isoformat(), "container_number": shipment.container_number,
        "seal_number": shipment.seal_number, "export_document_ref": shipment.export_document_ref,
        "bill_of_lading": shipment.bill_of_lading, "late_reason_code": shipment.late_reason_code,
    }


@transaction.atomic
def create_shipment(*, tenant_id, user, customer, lines, shipped_at=None, container_number="", seal_number="",
                    export_document_ref="", bill_of_lading="", site=None, late_reason_code="", late_comment=""):
    """Expedition d'un ou plusieurs lots (palettes, cartons) vers un client. `lines` = [(lot, quantite, unite)]."""
    errors = {}
    if not customer.is_customer:
        errors["customer"] = ["Ce partenaire n'est pas un client."]
    if not customer.is_active:
        errors["customer"] = ["Ce client est désactivé."]
    if not lines:
        errors["lines"] = ["Ajoutez au moins un lot."]
    container_number = normalize_container(container_number)
    if container_number and not CONTAINER_RE.match(container_number):
        errors["container_number"] = ["N° de conteneur : 4 lettres puis 7 chiffres (ex. MSCU1234567)."]
    lot_ids = [lot.id for lot, _, _ in lines]
    if len(set(lot_ids)) != len(lot_ids):
        errors["lines"] = ["Un même lot apparaît deux fois : regroupez les quantités."]
    if errors:
        raise ValidationError(errors)
    shipped_at, late_reason_code, late_comment = lots.check_entry_time(shipped_at, late_reason_code, late_comment,
                                                                       field="shipped_at")
    site = lots.default_site(site)
    shipment = Shipment.objects.create(
        tenant_id=tenant_id, customer=customer, site=site, shipped_at=shipped_at, container_number=container_number,
        seal_number=seal_number.strip(), export_document_ref=export_document_ref.strip(),
        bill_of_lading=bill_of_lading.strip(), user=user, late_reason_code=late_reason_code, late_comment=late_comment,
    )
    for lot, quantity, unit in lines:
        base = lots.to_base_quantity(article=lot.article, quantity=quantity, unit=unit or lot.article.base_unit)
        movement = lots.record_exit(
            tenant_id=tenant_id, user=user, lot_id=lot.id, movement_type=Movement.Type.EXPEDITION, quantity=base,
            partner=customer, occurred_at=shipped_at, late_reason_code=late_reason_code, late_comment=late_comment,
        )
        ShipmentLine.objects.create(tenant_id=tenant_id, shipment=shipment, lot=lot, quantity=base, movement=movement)
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=shipment, new_values=_values(shipment))
    publish_event(tenant_id=tenant_id, event_type="shipment.created",
                  payload={"shipment_id": str(shipment.id), "lines": len(lines)})
    return shipment
