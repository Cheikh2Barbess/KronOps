"""Regles metier des lots et mouvements. Toute ecriture passe par ici.

Regles du PRD appliquees : quantites en unite de base, decimal exact (3 decimales), jamais de stock
negatif, lot bloque ou perime ni consommable ni expediable, annulation = contre-mouvement avec motif.
"""

import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.services import record_audit
from catalog.models import Article
from events.services import publish_event
from lots import reasons, selectors
from lots.models import ApprovalRequest, Lot, LotLink, Movement
from tenants.models import User

THOUSANDTH = Decimal("0.001")
DOUBLE_VALIDATED_TYPES = {Movement.Type.REBUT, Movement.Type.AJUSTEMENT, Movement.Type.DESTRUCTION}


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
        "block_code": lot.block_code, "block_reason": lot.block_reason,
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
        block_code=reasons.RECEPTION_NON_CONFORME if block_reason else "",
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
    if lot.status == Lot.Status.DETRUIT:
        raise ValidationError({"lot": [f"Le lot {lot.code} est détruit."]})
    # Un lot bloque ne part ni en production ni chez un client. Rebut et destruction restent possibles.
    if lot.status == Lot.Status.BLOQUE and movement_type not in (Movement.Type.REBUT, Movement.Type.DESTRUCTION):
        raise ValidationError({"lot": [f"Le lot {lot.code} est bloqué."]})
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
def block_lot(*, tenant_id, user, lot_id, reason_code, comment=""):
    """Blocage immediat, motif choisi dans une liste fermee (commentaire seulement pour « Autre »)."""
    reason_code, comment = reasons.check(reasons.BLOCK, reason_code, comment)
    lot = _lock(lot_id)
    if lot.status != Lot.Status.DISPONIBLE:
        raise ValidationError({"lot": [f"Le lot {lot.code} est déjà {lot.get_status_display().lower()}."]})
    old = _lot_values(lot)
    lot.status, lot.block_code = Lot.Status.BLOQUE, reason_code
    lot.block_reason = reasons.text(reasons.BLOCK, reason_code, comment)
    lot.save(update_fields=["status", "block_code", "block_reason", "updated_at"])
    record_audit(tenant_id=tenant_id, user=user, action="block", entity=lot, old_values=old, new_values=_lot_values(lot))
    publish_event(tenant_id=tenant_id, event_type="lot.blocked",
                  payload={"lot_id": str(lot.id), "reason_code": reason_code})
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
    if movement.movement_type in DOUBLE_VALIDATED_TYPES:
        # Sinon une seule personne pourrait defaire ce que deux ont valide (US-20).
        raise ValidationError({"movement": [
            "Un rebut, un ajustement ou une destruction ne s'annule pas seul : faites une demande d'ajustement."
        ]})
    if lot.status == Lot.Status.DETRUIT:
        raise ValidationError({"movement": [f"Le lot {lot.code} est détruit."]})
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


# Double validation (US-20) ---------------------------------------------------
# Matrice des droits du PRD : qui peut DEMANDER chaque action, qui peut VALIDER.
# Deblocage et destruction : la Qualite demande (cycle de vie du lot).

A = ApprovalRequest.Action
R = User.Role
CAN_REQUEST = {
    A.RELEASE: {R.QUALITE},
    A.DESTROY: {R.QUALITE},
    A.SCRAP: {R.QUALITE, R.PRODUCTION, R.OPERATEUR},
    A.ADJUST: {R.QUALITE, R.PRODUCTION},
}
CAN_VALIDATE = {R.ADMIN, R.QUALITE, R.PRODUCTION}


def _approval_values(req):
    return {
        "action": req.action, "lot_id": str(req.lot_id), "quantity": str(req.quantity) if req.quantity is not None else None,
        "reason_code": req.reason_code, "comment": req.comment, "status": req.status,
        "decided_by": req.decided_by.username if req.decided_by_id else None,
        "decision_code": req.decision_code, "decision_comment": req.decision_comment,
    }


def _check_action_possible(*, lot, action, quantity):
    """Verifie que l'action a un sens sur le lot. Appelee a la demande ET a la validation (le stock a pu changer)."""
    if lot.status == Lot.Status.DETRUIT:
        raise ValidationError({"lot": [f"Le lot {lot.code} est détruit."]})
    if action in (A.RELEASE, A.DESTROY) and lot.status != Lot.Status.BLOQUE:
        raise ValidationError({"lot": [f"Le lot {lot.code} n'est pas bloqué : bloquez-le d'abord."]})
    if action == A.SCRAP:
        if quantity is None or quantity <= 0:
            raise ValidationError({"quantity": ["Quantité de rebut obligatoire et strictement positive."]})
    if action == A.ADJUST and (quantity is None or quantity == 0):
        raise ValidationError({"quantity": ["Quantité d'ajustement obligatoire, positive ou négative, non nulle."]})
    if quantity is not None and quantity != quantity.quantize(THOUSANDTH):
        raise ValidationError({"quantity": ["3 décimales au maximum."]})
    balance = selectors.lot_balance(lot.id)
    removed = quantity if action == A.SCRAP else (-quantity if action == A.ADJUST and quantity < 0 else 0)
    if removed > balance:
        raise ValidationError({"quantity": [f"Quantité supérieure au solde du lot ({balance})."]})


@transaction.atomic
def request_approval(*, tenant_id, user, lot_id, action, reason_code, comment="", quantity=None):
    if user.role not in CAN_REQUEST.get(action, set()):
        raise PermissionDenied("Votre rôle ne permet pas de demander cette action.")
    reason_code, comment = reasons.check(reasons.APPROVAL[action], reason_code, comment)
    lot = _lock(lot_id)
    if action in (A.RELEASE, A.DESTROY):
        quantity = None
    _check_action_possible(lot=lot, action=action, quantity=quantity)
    pending = ApprovalRequest.objects.filter(lot=lot, action=action, status=ApprovalRequest.Status.PENDING)
    if action in (A.RELEASE, A.DESTROY) and pending.exists():
        raise ValidationError({"lot": ["Une demande identique est déjà en attente pour ce lot."]})
    req = ApprovalRequest.objects.create(
        tenant_id=tenant_id, action=action, lot=lot, quantity=quantity, reason_code=reason_code, comment=comment,
        requested_by=user, requested_role=user.role,
    )
    record_audit(tenant_id=tenant_id, user=user, action="request", entity=req, new_values=_approval_values(req))
    publish_event(tenant_id=tenant_id, event_type="approval.requested",
                  payload={"approval_id": str(req.id), "action": action, "lot_id": str(lot.id)})
    return req


def _lock_pending(request_id):
    req = ApprovalRequest.objects.select_for_update().filter(pk=request_id).first()
    if req is None:
        raise ValidationError({"request": ["Demande introuvable."]})
    if req.status != ApprovalRequest.Status.PENDING:
        raise ValidationError({"request": [f"Cette demande est déjà {req.get_status_display().lower()}."]})
    return req


def _check_validator(req, user):
    if user.role not in CAN_VALIDATE:
        raise PermissionDenied("Votre rôle ne permet pas de valider une demande.")
    if req.requested_by_id == user.id:
        raise ValidationError({"request": ["Vous ne pouvez pas valider votre propre demande."]})
    if req.requested_role == user.role:
        raise ValidationError({"request": ["La validation doit venir d'un utilisateur d'un autre rôle que le demandeur."]})


def _decide(req, user, status, code="", comment=""):
    old = _approval_values(req)
    req.status, req.decided_by, req.decided_role = status, user, user.role
    req.decided_at, req.decision_code, req.decision_comment = timezone.now(), code, comment
    req.save(update_fields=["status", "decided_by", "decided_role", "decided_at", "decision_code",
                            "decision_comment", "movement", "updated_at"])
    return old


def approval_reason_text(req):
    return reasons.text(reasons.APPROVAL[req.action], req.reason_code, req.comment)


@transaction.atomic
def approve_request(*, tenant_id, user, request_id):
    """Valide la demande ET execute l'action, dans la meme transaction."""
    req = _lock_pending(request_id)
    _check_validator(req, user)
    lot = _lock(req.lot_id)
    _check_action_possible(lot=lot, action=req.action, quantity=req.quantity)
    # Le mouvement est enregistre au moment de la validation, donc au nom du validateur. Le demandeur
    # reste visible dans le motif et dans la demande liee.
    who, reason = user, f"{approval_reason_text(req)} (demandé par {req.requested_by.username})"
    if req.action == A.RELEASE:
        old = _lot_values(lot)
        lot.status, lot.block_code, lot.block_reason = Lot.Status.DISPONIBLE, "", ""
        lot.save(update_fields=["status", "block_code", "block_reason", "updated_at"])
        record_audit(tenant_id=tenant_id, user=user, action="release", entity=lot, old_values=old,
                     new_values=_lot_values(lot))
        publish_event(tenant_id=tenant_id, event_type="lot.released", payload={"lot_id": str(lot.id)})
    elif req.action == A.DESTROY:
        balance = selectors.lot_balance(lot.id)
        if balance > 0:
            req.movement = _movement(tenant_id=tenant_id, user=who, lot=lot, movement_type=Movement.Type.DESTRUCTION,
                                     quantity=-balance, reason=reason)
        old = _lot_values(lot)
        lot.status = Lot.Status.DETRUIT
        lot.save(update_fields=["status", "updated_at"])
        record_audit(tenant_id=tenant_id, user=user, action="destroy", entity=lot, old_values=old,
                     new_values=_lot_values(lot))
        publish_event(tenant_id=tenant_id, event_type="lot.destroyed", payload={"lot_id": str(lot.id)})
    elif req.action == A.SCRAP:
        req.movement = _movement(tenant_id=tenant_id, user=who, lot=lot, movement_type=Movement.Type.REBUT,
                                 quantity=-req.quantity, reason=reason)
    else:
        req.movement = _movement(tenant_id=tenant_id, user=who, lot=lot, movement_type=Movement.Type.AJUSTEMENT,
                                 quantity=req.quantity, reason=reason)
    if req.action in (A.SCRAP, A.ADJUST, A.DESTROY) and selectors.lot_balance(lot.id) == 0:
        publish_event(tenant_id=tenant_id, event_type="lot.depleted", payload={"lot_id": str(lot.id)})
    old = _decide(req, user, ApprovalRequest.Status.APPROVED)
    record_audit(tenant_id=tenant_id, user=user, action="approve", entity=req, old_values=old,
                 new_values=_approval_values(req))
    publish_event(tenant_id=tenant_id, event_type="approval.approved", payload={"approval_id": str(req.id)})
    return req


@transaction.atomic
def reject_request(*, tenant_id, user, request_id, reason_code, comment=""):
    reason_code, comment = reasons.check(reasons.REJECT, reason_code, comment)
    req = _lock_pending(request_id)
    _check_validator(req, user)
    old = _decide(req, user, ApprovalRequest.Status.REJECTED, reason_code, comment)
    record_audit(tenant_id=tenant_id, user=user, action="reject", entity=req, old_values=old,
                 new_values=_approval_values(req))
    publish_event(tenant_id=tenant_id, event_type="approval.rejected", payload={"approval_id": str(req.id)})
    return req


@transaction.atomic
def cancel_request(*, tenant_id, user, request_id):
    req = _lock_pending(request_id)
    if req.requested_by_id != user.id:
        raise PermissionDenied("Seul le demandeur peut annuler sa demande.")
    old = _approval_values(req)
    req.status = ApprovalRequest.Status.CANCELLED
    req.save(update_fields=["status", "updated_at"])
    record_audit(tenant_id=tenant_id, user=user, action="cancel", entity=req, old_values=old,
                 new_values=_approval_values(req))
    publish_event(tenant_id=tenant_id, event_type="approval.cancelled", payload={"approval_id": str(req.id)})
    return req
