"""Reglages du tableau de bord par l'Admin de l'entreprise : seuils des couleurs et cibles de production."""

import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from dashboard.indicators import HIGHER, THRESHOLDS
from dashboard.models import DashboardThreshold, ProductionTarget
from dashboard import reasons
from events.services import publish_event
from lots import reasons as lot_reasons


def _values(row):
    return {"code": row.code, "green": str(row.green), "red": str(row.red)}


@transaction.atomic
def set_threshold(*, tenant_id, user, code, green, red):
    if code not in THRESHOLDS:
        raise ValidationError({"code": ["Indicateur inconnu."]})
    item = THRESHOLDS[code]
    green, red = Decimal(green), Decimal(red)
    if item["unit"] == "%" and not (0 <= green <= 100 and 0 <= red <= 100):
        raise ValidationError({"green": ["Un pourcentage va de 0 à 100."]})
    if item["unit"] in ("lots", "h") and (green < 0 or red < 0):
        raise ValidationError({"green": ["Le seuil ne peut pas être négatif."]})
    if item["direction"] == HIGHER and green < red:
        raise ValidationError({"green": ["Ici, plus c'est haut, mieux c'est : le seuil vert doit être au moins égal au seuil rouge."]})
    if item["direction"] != HIGHER and green > red:
        raise ValidationError({"green": ["Ici, plus c'est bas, mieux c'est : le seuil vert doit être au plus égal au seuil rouge."]})

    row = DashboardThreshold.objects.select_for_update().filter(code=code).first()
    if row is None:
        row = DashboardThreshold.objects.create(tenant_id=tenant_id, code=code, green=green, red=red)
        record_audit(tenant_id=tenant_id, user=user, action="create", entity=row, new_values=_values(row))
    else:
        old = _values(row)
        if (row.green, row.red) == (green, red):
            return row
        row.green, row.red = green, red
        row.save(update_fields=["green", "red", "updated_at"])
        record_audit(tenant_id=tenant_id, user=user, action="update", entity=row, old_values=old,
                     new_values=_values(row))
    publish_event(tenant_id=tenant_id, event_type="dashboard.threshold_changed", payload=_values(row))
    return row


@transaction.atomic
def reset_threshold(*, tenant_id, user, code):
    """Retour a la valeur par defaut : le reglage de l'entreprise est retire (trace au journal)."""
    if code not in THRESHOLDS:
        raise ValidationError({"code": ["Indicateur inconnu."]})
    row = DashboardThreshold.objects.select_for_update().filter(code=code).first()
    if row is None:
        return
    record_audit(tenant_id=tenant_id, user=user, action="delete", entity=row, old_values=_values(row))
    row.delete()
    publish_event(tenant_id=tenant_id, event_type="dashboard.threshold_reset", payload={"code": code})


# Cibles de production ---------------------------------------------------------------------


@transaction.atomic
def set_targets(*, tenant_id, user, article, year, months, reason_code="", reason_comment=""):
    """Cibles d'un article pour les 12 mois d'une annee. `months` = 12 valeurs (unite de base) ou None (pas de cible).

    Une cible changee ou retiree passe au journal d'audit (ancienne et nouvelle valeur), avec un evenement. Changer
    ou retirer une cible deja saisie demande un motif dans une liste fermee (la premiere saisie n'en demande pas).
    """
    from dashboard.product_selectors import target_articles

    if not target_articles().filter(pk=article.pk).exists():
        raise ValidationError({"article": ["Seuls les produits (semi-finis et finis actifs) reçoivent une cible."]})
    if not 2000 <= int(year) <= 2100:
        raise ValidationError({"year": ["Année invalide."]})
    if len(months) != 12:
        raise ValidationError({"months": ["Il faut 12 valeurs, une par mois (vide si pas de cible)."]})
    wanted = {}
    for index, value in enumerate(months):
        if value in (None, ""):
            continue
        try:
            value = Decimal(str(value))
        except InvalidOperation:
            raise ValidationError({"months": [f"Mois {index + 1} : nombre attendu."]})
        if value <= 0:
            raise ValidationError({"months": [f"Mois {index + 1} : la cible doit être positive (vide pour aucune)."]})
        wanted[datetime.date(int(year), index + 1, 1)] = value.quantize(Decimal("0.001"))
    existing = {t.month: t for t in ProductionTarget.objects.select_for_update().filter(article=article,
                                                                                         month__year=year)}
    touched = [m for m, row in existing.items() if wanted.get(m) != row.quantity]
    reason = ""
    if touched:
        if not reason_code:
            raise ValidationError({"reason_code": ["Une cible déjà saisie change : choisissez le motif."]})
        reason_code, reason_comment = lot_reasons.check(reasons.TARGET_CHANGE, reason_code, reason_comment,
                                                        field="reason_code")
        reason = lot_reasons.text(reasons.TARGET_CHANGE, reason_code, reason_comment)
    changed = []
    for month in sorted(set(existing) | set(wanted)):
        row, value = existing.get(month), wanted.get(month)
        if row is None:
            row = ProductionTarget.objects.create(tenant_id=tenant_id, article=article, month=month, quantity=value)
            record_audit(tenant_id=tenant_id, user=user, action="create", entity=row, new_values=_target_values(row))
        elif value is None:
            record_audit(tenant_id=tenant_id, user=user, action="delete", entity=row, old_values=_target_values(row),
                         new_values={"reason_code": reason_code, "reason": reason})
            row.delete()
        elif row.quantity != value:
            old = _target_values(row)
            row.quantity = value
            row.save(update_fields=["quantity", "updated_at"])
            record_audit(tenant_id=tenant_id, user=user, action="update", entity=row, old_values=old,
                         new_values={**_target_values(row), "reason_code": reason_code, "reason": reason})
        else:
            continue
        changed.append(month.isoformat())
    if changed:
        publish_event(tenant_id=tenant_id, event_type="dashboard.targets_changed",
                      payload={"article_id": str(article.id), "months": changed, "reason_code": reason_code})


def _target_values(row):
    return {"article_id": str(row.article_id), "month": row.month.isoformat(), "quantity": str(row.quantity)}
