"""Reglage des seuils du tableau de bord (Admin de l'entreprise)."""

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from dashboard.indicators import HIGHER, THRESHOLDS
from dashboard.models import DashboardThreshold
from events.services import publish_event


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
