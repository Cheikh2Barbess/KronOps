"""Regles metier des expeditions. Toute ecriture passe par ici."""

import re

from django.db import transaction
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from events.services import publish_event
from lots import selectors as lot_selectors
from lots import services as lots
from lots.models import Movement
from production.pipeline import require_module
from shipping.models import Shipment, ShipmentLine

# Format ISO 6346 : 3 lettres du proprietaire, 1 lettre de categorie, 6 chiffres et 1 chiffre de controle.
CONTAINER_RE = re.compile(r"^[A-Z]{4}\d{7}$")


def _letter_values():
    # A = 10, puis +1 par lettre en sautant les multiples de 11 (11, 22, 33) : regle ISO 6346.
    values, n = {}, 10
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if n % 11 == 0:
            n += 1
        values[letter] = n
        n += 1
    return values


LETTER_VALUES = _letter_values()


def container_check_digit(first_ten):
    """Chiffre de controle ISO 6346 des 10 premiers caracteres (ex. CSQU305438 -> 3)."""
    total = sum((LETTER_VALUES[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(first_ten))
    return total % 11 % 10


def normalize_container(number):
    return re.sub(r"[\s-]", "", number or "").upper()


def container_error(number):
    """Message d'erreur pour un n° de conteneur deja normalise, ou "" s'il est valable."""
    if not CONTAINER_RE.match(number):
        return "N° de conteneur : 4 lettres puis 7 chiffres (ex. CSQU3054383)."
    if container_check_digit(number[:10]) != int(number[10]):
        return (f"N° de conteneur {number} : le dernier chiffre (chiffre de contrôle) ne correspond pas. "
                "Vérifiez la saisie sur la porte du conteneur.")
    return ""


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
    require_module("expedition")
    errors = {}
    if not customer.is_customer:
        errors["customer"] = ["Ce partenaire n'est pas un client."]
    if not customer.is_active:
        errors["customer"] = ["Ce client est désactivé."]
    if not lines:
        errors["lines"] = ["Ajoutez au moins un lot."]
    container_number = normalize_container(container_number)
    if container_number and container_error(container_number):
        errors["container_number"] = [container_error(container_number)]
    lot_ids = [lot.id for lot, _, _ in lines]
    if len(set(lot_ids)) != len(lot_ids):
        errors["lines"] = ["Un même lot apparaît deux fois : regroupez les quantités."]
    if errors:
        raise ValidationError(errors)
    shipped_at, late_reason_code, late_comment = lots.check_entry_time(shipped_at, late_reason_code, late_comment,
                                                                       field="shipped_at")
    site = lots.default_site(site)
    for lot, _, _ in lines:
        if site is not None and lot.site_id and lot.site_id != site.id:
            raise ValidationError({"lines": [
                f"Le lot {lot.code} est à {lot.site.name}, pas à {site.name} : transférez-le d'abord."
            ]})
        ok, why = lot_selectors.quality_clearance(lot)
        if not ok:
            raise ValidationError({"lines": [why]})
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
