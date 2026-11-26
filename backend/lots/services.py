"""Regles metier des lots et mouvements. Toute ecriture passe par ici.

Regles du PRD appliquees : quantites en unite de base, decimal exact (3 decimales), jamais de stock
negatif, lot bloque ou perime ni consommable ni expediable, annulation = contre-mouvement avec motif.
"""

import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from catalog.models import Article
from events.services import publish_event
from lots import selectors
from lots.models import Lot, LotLink, Movement

THOUSANDTH = Decimal("0.001")


def to_base_quantity(*, article, quantity, unit):
    """Convertit une quantite saisie (unite de base ou conditionnement de l'article) en unite de base."""
    if quantity <= 0:
        raise ValidationError({"quantity": ["La quantité doit être strictement positive."]})
    if unit == article.base_unit:
        factor = Decimal("1")
    else:
        conversion = article.conversions.filter(unit_name__iexact=unit).first()
        if conversion is None:
            raise ValidationError({"unit": [f"Unité « {unit} » inconnue pour l'article {article.code}."]})
        factor = conversion.factor
    base = quantity * factor
    if base != base.quantize(THOUSANDTH):
        # Pas d'arrondi dans le calcul (regle Unites du PRD) : on refuse plutot que d'arrondir.
        raise ValidationError({"quantity": ["La quantité convertie dépasse 3 décimales. Saisissez-la en unité de base."]})
    return base.quantize(THOUSANDTH)


def _next_lot_code(article, day):
    # Verrou sur l'article : deux receptions simultanees ne peuvent pas prendre le meme numero.
    Article.objects.select_for_update().get(pk=article.pk)
    prefix = f"{article.code}-{day:%y%m%d}-"
    n = Lot.objects.filter(code__startswith=prefix).count() + 1
    return f"{prefix}{n:02d}"


def _lock(lot_id):
    lot = Lot.objects.select_for_update().filter(pk=lot_id).first()
    if lot is None:
        raise ValidationError({"lot": ["Lot introuvable."]})
    return lot


def is_expired(lot, today=None):
    today = today or timezone.localdate()
    return lot.date_type == Lot.DateType.DLC and lot.expiry_date is not None and lot.expiry_date < today


def _lot_values(lot):
    return {
        "code": lot.code, "article_id": str(lot.article_id), "status": lot.status,
        "supplier_id": str(lot.supplier_id) if lot.supplier_id else None, "supplier_lot_code": lot.supplier_lot_code,
        "date_type": lot.date_type, "expiry_date": lot.expiry_date.isoformat() if lot.expiry_date else None,
        "block_reason": lot.block_reason,
    }


def _movement(*, tenant_id, user, lot, movement_type, quantity, partner=None, reason="", occurred_at=None, reverses=None):
    movement = Movement.objects.create(
        tenant_id=tenant_id, lot=lot, movement_type=movement_type, quantity=quantity, partner=partner,
        reason=reason, occurred_at=occurred_at or timezone.now(), user=user, reverses=reverses,
    )
    record_audit(
        tenant_id=tenant_id, user=user, action="create", entity=movement,
        new_values={"lot_id": str(lot.id), "type": movement_type, "quantity": str(quantity), "reason": reason,
                    "partner_id": str(partner.id) if partner else None},
    )
    publish_event(
        tenant_id=tenant_id, event_type="movement.recorded",
        payload={"movement_id": str(movement.id), "lot_id": str(lot.id), "type": movement_type,
                 "quantity": str(quantity)},
    )
    return movement


# Creation de lots --------------------------------------------------------


@transaction.atomic
def create_lot(*, tenant_id, user, article, quantity, entry_type, supplier=None, supplier_lot_code="",
               date_type="", expiry_date=None, temperature_c=None, visual_ok=None, block_reason="",
               occurred_at=None):
    """Brique commune : cree un lot et son mouvement d'entree (reception ou production)."""
    if entry_type not in (Movement.Type.RECEPTION, Movement.Type.PRODUCTION):
        raise ValidationError({"entry_type": ["Type d'entrée invalide."]})
    when = occurred_at or timezone.now()
    day = timezone.localtime(when).date() if isinstance(when, datetime.datetime) else when
    lot = Lot.objects.create(
        tenant_id=tenant_id, article=article, code=_next_lot_code(article, day), supplier=supplier,
        supplier_lot_code=supplier_lot_code, date_type=date_type if expiry_date else "", expiry_date=expiry_date,
        production_date=day, reception_temperature_c=temperature_c, reception_visual_ok=visual_ok,
        status=Lot.Status.BLOQUE if block_reason else Lot.Status.DISPONIBLE, block_reason=block_reason,
    )
    _movement(
        tenant_id=tenant_id, user=user, lot=lot, movement_type=entry_type, quantity=quantity, partner=supplier,
        occurred_at=when,
    )
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=lot, new_values=_lot_values(lot))
    publish_event(tenant_id=tenant_id, event_type="lot.created", payload={"lot_id": str(lot.id), "code": lot.code})
    if block_reason:
        publish_event(
            tenant_id=tenant_id, event_type="lot.blocked", payload={"lot_id": str(lot.id), "reason": block_reason}
        )
    return lot


@transaction.atomic
def receive_lot(*, tenant_id, user, article, supplier, supplier_lot_code, quantity, unit, date_type=None,
                expiry_date=None, visual_ok=True, temperature_c=None, reason="", occurred_at=None):
    """US-04 (partie API) : reception d'un lot fournisseur."""
    errors = {}
    if not supplier.is_supplier:
        errors["supplier"] = ["Ce partenaire n'est pas un fournisseur."]
    if not article.is_active:
        errors["article"] = ["Cet article est désactivé."]
    if article.article_type != Article.Type.EMBALLAGE and not expiry_date:
        errors["expiry_date"] = ["DLC ou DDM obligatoire pour cet article."]
    if expiry_date and not date_type:
        errors["date_type"] = ["Préciser s'il s'agit d'une DLC ou d'une DDM."]
    if article.storage in (Article.Storage.REFRIGERE, Article.Storage.CONGELE) and temperature_c is None:
        errors["temperature_c"] = ["Température à réception obligatoire pour un article réfrigéré ou congelé."]
    if not visual_ok and not reason.strip():
        errors["reason"] = ["Motif obligatoire quand la réception n'est pas conforme."]
    if errors:
        raise ValidationError(errors)
    base_quantity = to_base_quantity(article=article, quantity=quantity, unit=unit)
    return create_lot(
        tenant_id=tenant_id, user=user, article=article, quantity=base_quantity, entry_type=Movement.Type.RECEPTION,
        supplier=supplier, supplier_lot_code=supplier_lot_code, date_type=date_type or "", expiry_date=expiry_date,
        temperature_c=temperature_c, visual_ok=visual_ok,
        # Reception non conforme : le lot nait bloque (cycle de vie du PRD).
        block_reason="" if visual_ok else reason.strip(), occurred_at=occurred_at,
    )


# Sorties, blocage, annulation --------------------------------------------


@transaction.atomic
def record_exit(*, tenant_id, user, lot_id, movement_type, quantity, partner=None, reason="", occurred_at=None):
    """Brique commune des sorties (consommation, expedition, rebut...). Appelee par les futures US-07 et US-09."""
    if movement_type not in Movement.EXIT_TYPES:
        raise ValidationError({"movement_type": ["Type de sortie invalide."]})
    if quantity <= 0:
        raise ValidationError({"quantity": ["La quantité doit être strictement positive."]})
    lot = _lock(lot_id)
    if lot.status != Lot.Status.DISPONIBLE and movement_type != Movement.Type.DESTRUCTION:
        raise ValidationError({"lot": [f"Le lot {lot.code} est {lot.get_status_display().lower()}."]})
    if is_expired(lot) and movement_type in (Movement.Type.CONSOMMATION, Movement.Type.EXPEDITION):
        raise ValidationError({"lot": [f"Le lot {lot.code} est périmé (DLC dépassée)."]})
    balance = selectors.lot_balance(lot.id)
    if quantity > balance:
        raise ValidationError({"quantity": [f"Quantité supérieure au solde du lot ({balance})."]})
    movement = _movement(
        tenant_id=tenant_id, user=user, lot=lot, movement_type=movement_type, quantity=-quantity, partner=partner,
        reason=reason, occurred_at=occurred_at,
    )
    if balance - quantity == 0:
        publish_event(tenant_id=tenant_id, event_type="lot.depleted", payload={"lot_id": str(lot.id)})
    return movement


@transaction.atomic
def block_lot(*, tenant_id, user, lot_id, reason):
    if not reason or not reason.strip():
        raise ValidationError({"reason": ["Motif obligatoire."]})
    lot = _lock(lot_id)
    if lot.status != Lot.Status.DISPONIBLE:
        raise ValidationError({"lot": [f"Le lot {lot.code} est déjà {lot.get_status_display().lower()}."]})
    old = _lot_values(lot)
    lot.status, lot.block_reason = Lot.Status.BLOQUE, reason.strip()
    lot.save(update_fields=["status", "block_reason", "updated_at"])
    record_audit(tenant_id=tenant_id, user=user, action="block", entity=lot, old_values=old, new_values=_lot_values(lot))
    publish_event(tenant_id=tenant_id, event_type="lot.blocked", payload={"lot_id": str(lot.id), "reason": lot.block_reason})
    return lot


@transaction.atomic
def reverse_movement(*, tenant_id, user, movement_id, reason):
    """Annule un mouvement par un contre-mouvement lie, avec motif. Jamais de modification ni de suppression."""
    if not reason or not reason.strip():
        raise ValidationError({"reason": ["Motif obligatoire."]})
    movement = Movement.objects.filter(pk=movement_id).first()
    if movement is None:
        raise ValidationError({"movement": ["Mouvement introuvable."]})
    lot = _lock(movement.lot_id)
    if movement.movement_type == Movement.Type.ANNULATION:
        raise ValidationError({"movement": ["Une annulation ne s'annule pas. Saisissez un nouveau mouvement."]})
    if Movement.objects.filter(reverses=movement).exists():
        raise ValidationError({"movement": ["Ce mouvement est déjà annulé."]})
    if movement.movement_type in Movement.ENTRY_TYPES:
        # Une entree ne s'annule que si le lot n'a servi a rien depuis (cycle de vie du PRD).
        used = Movement.objects.filter(lot=lot).exclude(pk=movement.pk).exists()
        if used or LotLink.objects.filter(parent_lot=lot).exists():
            raise ValidationError({"movement": ["Le lot a déjà été utilisé : annulez d'abord les mouvements suivants."]})
    if selectors.lot_balance(lot.id) - movement.quantity < 0:
        raise ValidationError({"movement": ["Cette annulation rendrait le stock négatif."]})
    reversal = _movement(
        tenant_id=tenant_id, user=user, lot=lot, movement_type=Movement.Type.ANNULATION, quantity=-movement.quantity,
        partner=movement.partner, reason=reason.strip(), reverses=movement,
    )
    record_audit(
        tenant_id=tenant_id, user=user, action="cancel", entity=movement,
        old_values={"type": movement.movement_type, "quantity": str(movement.quantity)},
        new_values={"reversal_id": str(reversal.id), "reason": reversal.reason},
    )
    publish_event(
        tenant_id=tenant_id, event_type="movement.reversed",
        payload={"movement_id": str(movement.id), "reversal_id": str(reversal.id)},
    )
    return reversal


# Genealogie --------------------------------------------------------------


@transaction.atomic
def link_lots(*, tenant_id, user, parent, child):
    """Enregistre que `parent` entre dans la composition de `child`. Appele par la declaration de production."""
    if parent.pk == child.pk:
        raise ValidationError({"lot": ["Un lot ne peut pas entrer dans sa propre composition."]})
    link = LotLink.objects.create(tenant_id=tenant_id, parent_lot=parent, child_lot=child, user=user)
    record_audit(
        tenant_id=tenant_id, user=user, action="create", entity=link,
        new_values={"parent_lot_id": str(parent.id), "child_lot_id": str(child.id)},
    )
    publish_event(
        tenant_id=tenant_id, event_type="lot.linked",
        payload={"parent_lot_id": str(parent.id), "child_lot_id": str(child.id)},
    )
    return link
