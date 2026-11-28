"""Lectures des actions et calcul des alertes.

Une alerte n'est pas stockee : elle se calcule a chaque lecture a partir des saisies (produit sous la cible, arret
en cours trop long, lot bloque, action en retard). Elle dit si une action ouverte la couvre deja, sinon elle propose
de la creer (type et objet pre-remplis).
"""

import uuid

from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from actions import reasons
from actions.models import Action
from lots import reasons as lot_reasons
from lots import selectors as lot_selectors
from lots.models import Lot
from production import selectors as production_selectors

OPEN = (Action.Status.OUVERTE, Action.Status.EN_COURS)
STATUS_ORDER = {"bad": 0, "warn": 1, "info": 2, "ok": 3}


def actions(*, status="open", user=None, mine=False):
    qs = Action.objects.select_related("responsible", "created_by", "closed_by", "cancelled_by", "equipment",
                                       "lot", "article", "line_stop").order_by("due_date", "-created_at")
    if status == "open":
        qs = qs.filter(status__in=OPEN)
    elif status in Action.Status.values:
        qs = qs.filter(status=status)
    if mine and user is not None:
        qs = qs.filter(Q(responsible=user) | Q(created_by=user))
    return qs


def action_or_404(action_id):
    found = actions(status="all").filter(pk=action_id).first()
    if found is None:
        raise Http404
    return decorate(found)


def _fr(value):
    return f"{value:+.0f}".replace("-", "−") if value is not None else "inconnu"


def _name(user):
    return (user.get_full_name() or user.username) if user else None


def decorate(a, today=None):
    today = today or timezone.localdate()
    a.subject = reasons.subject_label(a.subject_code, a.comment)
    a.type_label = reasons.TYPES.get(a.action_type, a.action_type)
    a.late = a.status in OPEN and a.due_date < today
    a.result = reasons.RESULTS.get(a.result_code, "") if a.result_code else ""
    a.cancel_reason = (lot_reasons.text(reasons.CANCEL, a.cancel_reason_code, a.cancel_comment)
                       if a.cancelled_at else "")
    return a


def _open_index():
    """Actions ouvertes par lien (arret, lot, produit, equipement), pour dire si une alerte est deja couverte."""
    index = {}
    for a in actions(status="open"):
        for key in (("stop", a.line_stop_id), ("lot", a.lot_id), ("article", a.article_id)):
            if key[1] and key not in index:
                index[key] = a
    return index


def _covered(index, key):
    a = index.get(key)
    if a is None:
        return None
    return {"id": str(a.id), "status": a.get_status_display(), "responsible": _name(a.responsible), "due_date": a.due_date.isoformat(), "subject": reasons.subject_label(
                a.subject_code, a.comment)}


def alerts(*, status, target_rows):
    """Alertes du moment, la plus grave d'abord. `status(code, valeur)` colore selon les seuils de l'entreprise.
    `target_rows` : produits du mois avec leur atteinte de cible (dashboard.gap_selectors.products)."""
    now = timezone.now()
    today = timezone.localdate()
    index = _open_index()
    found = []
    for p in target_rows:
        if p["status"] not in ("bad", "warn"):
            continue
        found.append({
            "code": "target", "status": p["status"], "at": None,
            "title": f"{p['label']} à {p['attainment']:.0f} % de la cible ce mois-ci".replace(".", ","),
            "detail": f"Écart {_fr(p['gap'])} {p['unit']}" + (f", surtout {p['top_cause'].lower()}" if p["top_cause"] else ""),
            "href": f"/dashboard/ecart?article={p['article_id']}",
            "create": {"action_type": "production", "subject_code": "rattraper_retard", "article": p["article_id"]},
            "open_action": _covered(index, ("article", uuid.UUID(str(p["article_id"])))),
        })
    for stop in production_selectors.line_stops(include_cancelled=False).filter(ended_at__isnull=True):
        production_selectors.decorate_stop(stop, now=now)
        level = status("ongoing_stop_hours", stop.duration_hours)
        if level not in ("bad", "warn"):
            continue
        hours = f"{stop.duration_hours:.1f}".replace(".", ",")
        found.append({
            "code": "ongoing_stop", "status": level, "at": stop.started_at,
            "title": f"{stop.equipment.code} à l'arrêt depuis {hours} h",
            "detail": stop.cause_label, "href": f"/arrets?equipment={stop.equipment_id}",
            "create": {"action_type": "maintenance", "subject_code": "reparer_equipement", "line_stop": str(stop.id)},
            "open_action": _covered(index, ("stop", stop.id)),
        })
    # Comme la tuile « Lots bloqués » : seulement les lots qui ont encore du stock (sans stock, rien a decider).
    for lot in lot_selectors.lots().filter(status=Lot.Status.BLOQUE, balance__gt=0).order_by("code"):
        found.append({
            "code": "blocked_lot", "status": "warn", "at": None,
            "title": f"Lot {lot.code} bloqué", "detail": lot.article.name, "href": "/validations",
            "create": {"action_type": "qualite", "subject_code": "decider_lot", "lot": str(lot.id)},
            "open_action": _covered(index, ("lot", lot.id)),
        })
    for a in actions(status="open").filter(due_date__lt=today):
        decorate(a, today)
        found.append({
            "code": "late_action", "status": "bad", "at": None,
            "title": f"Action en retard : {a.subject}",
            "detail": f"{a.type_label}, échéance {a.due_date.strftime('%d/%m/%Y')}, "
                      f"{_name(a.responsible) or 'à attribuer'}",
            "href": "/actions", "create": None,
            "open_action": {"id": str(a.id), "status": a.get_status_display(), "responsible": _name(a.responsible),
                            "due_date": a.due_date.isoformat(), "subject": a.subject},
        })
    return sorted(found, key=lambda x: STATUS_ORDER.get(x["status"], 9))


def current_alerts(status=None):
    """Alertes du moment avec les seuils de l'entreprise. `status(code, valeur)` peut etre fourni par l'appelant
    (le tableau de bord a deja ses seuils), sinon il est construit ici."""
    from dashboard import gap_selectors
    from dashboard import selectors as dashboard_selectors
    from dashboard.indicators import status_for

    if status is None:
        t = dashboard_selectors.thresholds()

        def status(code, value):
            return status_for(value, direction=t[code]["direction"], green=t[code]["green"], red=t[code]["red"])

    rows = gap_selectors.products(lambda pct: status("target_attainment_pct", pct), "mois")["products"]
    return alerts(status=status, target_rows=rows)
