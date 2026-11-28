"""Actions : creer, attribuer, commencer, terminer, annuler. Chaque changement passe au journal avec un evenement."""

import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from actions import reasons
from actions.models import Action
from audit.services import record_audit
from events.services import publish_event
from lots import reasons as lot_reasons
from tenants.models import User

MANAGERS = (User.Role.ADMIN, User.Role.PRODUCTION, User.Role.QUALITE)


def _values(a):
    return {
        "action_type": a.action_type, "subject_code": a.subject_code, "comment": a.comment, "priority": a.priority,
        "origin": a.origin, "status": a.status, "responsible_id": str(a.responsible_id) if a.responsible_id else None,
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "line_stop_id": str(a.line_stop_id) if a.line_stop_id else None,
        "equipment_id": str(a.equipment_id) if a.equipment_id else None,
        "lot_id": str(a.lot_id) if a.lot_id else None, "article_id": str(a.article_id) if a.article_id else None,
        "result_code": a.result_code, "cancel_reason_code": a.cancel_reason_code,
    }


def _check_subject(action_type, subject_code, comment):
    if action_type not in reasons.TYPES:
        raise ValidationError({"action_type": ["Choisissez un type dans la liste."]})
    if subject_code not in reasons.SUBJECTS:
        raise ValidationError({"subject_code": ["Choisissez un objet dans la liste."]})
    subject_type = reasons.SUBJECTS[subject_code][0]
    if subject_type is not None and subject_type != action_type:
        raise ValidationError({"subject_code": ["Cet objet ne correspond pas au type d'action choisi."]})
    comment = (comment or "").strip()
    if subject_code == lot_reasons.OTHER and not comment:
        raise ValidationError({"comment": ["Précisez l'objet « Autre »."]})
    return comment


def _check_responsible(responsible):
    if responsible is not None and not responsible.is_active:
        raise ValidationError({"responsible": ["Ce compte est désactivé."]})


def _check_due(due_date):
    if due_date < timezone.localdate():
        raise ValidationError({"due_date": ["L'échéance ne peut pas être passée."]})


@transaction.atomic
def create_action(*, tenant_id, user, action_type, subject_code, due_date, comment="", priority="normale",
                  responsible=None, line_stop=None, equipment=None, lot=None, article=None, origin="saisie"):
    comment = _check_subject(action_type, subject_code, comment)
    if priority not in reasons.PRIORITIES:
        raise ValidationError({"priority": ["Choisissez une priorité dans la liste."]})
    if origin not in reasons.ORIGINS:
        raise ValidationError({"origin": ["Origine inconnue."]})
    _check_responsible(responsible)
    _check_due(due_date)
    if line_stop is not None and equipment is None:
        equipment = line_stop.equipment
    action = Action.objects.create(
        tenant_id=tenant_id, action_type=action_type, subject_code=subject_code, comment=comment, priority=priority,
        origin=origin, responsible=responsible, due_date=due_date, created_by=user, line_stop=line_stop,
        equipment=equipment, lot=lot, article=article,
    )
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=action, new_values=_values(action))
    publish_event(tenant_id=tenant_id, event_type="actions.action_created",
                  payload={"action_id": str(action.id), "action_type": action_type, "origin": origin,
                           "line_stop_id": str(line_stop.id) if line_stop else None})
    return action


@transaction.atomic
def call_from_post(*, tenant_id, user, line_stop, action_type):
    """Appel au poste : l'operateur demande la maintenance ou la qualite sur un arret. Priorite haute, pour aujourd'hui,
    a attribuer par un responsable."""
    if action_type not in ("maintenance", "qualite"):
        raise ValidationError({"action_type": ["Appel possible vers la maintenance ou la qualité."]})
    if line_stop.cancelled_at is not None:
        raise ValidationError({"line_stop": ["Cet arrêt est annulé."]})
    waiting = Action.objects.filter(line_stop=line_stop, action_type=action_type, origin="appel_poste",
                                    status__in=(Action.Status.OUVERTE, Action.Status.EN_COURS)).first()
    if waiting is not None:
        who = waiting.responsible.username if waiting.responsible else "personne pour l'instant"
        raise ValidationError({"line_stop": [f"{reasons.TYPES[action_type]} déjà appelée sur cet arrêt "
                                             f"(prise en charge : {who})."]})
    return create_action(tenant_id=tenant_id, user=user, action_type=action_type, subject_code="venir_au_poste",
                         due_date=timezone.localdate(), priority="haute", line_stop=line_stop, origin="appel_poste")


def _open(action_id):
    action = Action.objects.select_for_update().filter(pk=action_id).first()
    if action is None:
        raise NotFound("Action introuvable.")
    if action.status in (Action.Status.TERMINEE, Action.Status.ANNULEE):
        raise ValidationError({"status": [f"Cette action est déjà {action.get_status_display().lower()}."]})
    return action


def _may_move(user, action):
    """Un responsable (Admin, Production, Qualite) ou la personne chargee de l'action."""
    if user.role in MANAGERS or action.responsible_id == user.id:
        return
    raise PermissionDenied("Seul un responsable ou la personne chargée de l'action peut la faire avancer.")


def _save(action, user, tenant_id, old, fields, event, payload=None, audit_action="update"):
    action.save(update_fields=[*fields, "updated_at"])
    record_audit(tenant_id=tenant_id, user=user, action=audit_action, entity=action, old_values=old,
                 new_values=_values(action))
    publish_event(tenant_id=tenant_id, event_type=event, payload={"action_id": str(action.id), **(payload or {})})
    return action


@transaction.atomic
def assign_action(*, tenant_id, user, action_id, responsible, due_date=None, priority=None):
    if user.role not in MANAGERS:
        raise PermissionDenied("Seul un responsable attribue une action.")
    action = _open(action_id)
    _check_responsible(responsible)
    old = _values(action)
    action.responsible = responsible
    fields = ["responsible"]
    if due_date is not None:
        _check_due(due_date)
        action.due_date = due_date
        fields.append("due_date")
    if priority is not None:
        if priority not in reasons.PRIORITIES:
            raise ValidationError({"priority": ["Choisissez une priorité dans la liste."]})
        action.priority = priority
        fields.append("priority")
    return _save(action, user, tenant_id, old, fields, "actions.action_assigned",
                 {"responsible_id": str(responsible.id) if responsible else None})


@transaction.atomic
def start_action(*, tenant_id, user, action_id):
    action = _open(action_id)
    _may_move(user, action)
    if action.status == Action.Status.EN_COURS:
        raise ValidationError({"status": ["Cette action est déjà commencée."]})
    old = _values(action)
    action.status, action.started_at = Action.Status.EN_COURS, timezone.now()
    if action.responsible_id is None:
        action.responsible = user  # qui commence une action a attribuer la prend en charge
    return _save(action, user, tenant_id, old, ["status", "started_at", "responsible"], "actions.action_started")


@transaction.atomic
def close_action(*, tenant_id, user, action_id, result_code, comment=""):
    if result_code not in reasons.RESULTS:
        raise ValidationError({"result_code": ["Choisissez un résultat dans la liste."]})
    action = _open(action_id)
    _may_move(user, action)
    old = _values(action)
    action.status, action.closed_at, action.closed_by = Action.Status.TERMINEE, timezone.now(), user
    action.result_code, action.result_comment = result_code, (comment or "").strip()
    return _save(action, user, tenant_id, old, ["status", "closed_at", "closed_by", "result_code", "result_comment"],
                 "actions.action_closed", {"result_code": result_code})


@transaction.atomic
def cancel_action(*, tenant_id, user, action_id, reason_code, comment=""):
    if user.role not in MANAGERS:
        raise PermissionDenied("Seul un responsable annule une action.")
    reason_code, comment = lot_reasons.check(reasons.CANCEL, reason_code, comment)
    action = _open(action_id)
    old = _values(action)
    action.status, action.cancelled_at, action.cancelled_by = Action.Status.ANNULEE, timezone.now(), user
    action.cancel_reason_code, action.cancel_comment = reason_code, comment
    return _save(action, user, tenant_id, old,
                 ["status", "cancelled_at", "cancelled_by", "cancel_reason_code", "cancel_comment"],
                 "actions.action_cancelled", {"reason_code": reason_code}, audit_action="cancel")


def default_due(priority):
    return timezone.localdate() + datetime.timedelta(days=0 if priority == "haute" else 7)
