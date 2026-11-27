"""Regles metier de la declaration d'etape de production. Toute ecriture passe par ici.

Une declaration = un lot produit, a partir d'un ou plusieurs lots consommes en tout ou en partie.
Controles : pas de melange bio et non bio, pas plus de produit que de matiere, pas de consommation avant
l'entree du lot, saisie tardive justifiee. Le rendement hors fourchette est signale, pas bloque.
"""

import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from catalog.models import Article, OrganicStatus
from events.services import publish_event
from lots import reasons as lot_reasons
from lots import services as lots
from lots.models import Lot, Movement
from production import reasons
from production.models import Equipment, ProductionInput, ProductionRun

ORGANIC_LABEL = dict(OrganicStatus.choices)


def counts_in_balance(lot, output_article):
    """Une matiere compte dans le bilan si elle est dans la meme unite que le produit et n'est pas un emballage."""
    return lot.article.article_type != Article.Type.EMBALLAGE and lot.article.base_unit == output_article.base_unit


def output_organic_status(input_lots):
    """Statut bio du produit. Melanger des statuts differents est interdit (separation, reglement (UE) 2018/848)."""
    statuses = {lot.organic_status for lot in input_lots if lot.article.article_type != Article.Type.EMBALLAGE}
    if len(statuses) > 1:
        detail = ", ".join(
            f"{lot.code} ({ORGANIC_LABEL.get(lot.organic_status, 'statut bio non renseigné')})"
            for lot in input_lots if lot.article.article_type != Article.Type.EMBALLAGE
        )
        raise ValidationError({"inputs": [
            f"Mélange interdit : ces lots n'ont pas le même statut bio. {detail}."
        ]})
    return statuses.pop() if statuses else ""


def yield_status(run):
    """« sans_reference », « conforme », « bas » ou « haut »."""
    if run.input_quantity == 0 or run.yield_min_pct is None:
        return "sans_reference"
    pct = run.output_quantity * 100 / run.input_quantity
    if pct < run.yield_min_pct:
        return "bas"
    if pct > run.yield_max_pct:
        return "haut"
    return "conforme"


def _run_values(run):
    return {
        "step": run.step, "equipment_id": str(run.equipment_id) if run.equipment_id else None,
        "site_id": str(run.site_id) if run.site_id else None, "output_lot_id": str(run.output_lot_id),
        "input_quantity": str(run.input_quantity), "output_quantity": str(run.output_quantity),
        "waste_quantity": str(run.waste_quantity), "waste_code": run.waste_code,
        "started_at": run.started_at.isoformat(), "ended_at": run.ended_at.isoformat(),
        "late_reason_code": run.late_reason_code,
    }


@transaction.atomic
def declare_run(*, tenant_id, user, step, inputs, output_article, output_quantity, output_unit=None, equipment=None,
                site=None, started_at=None, ended_at=None, waste_quantity=None, waste_code="", waste_comment="",
                date_type="", expiry_date=None, late_reason_code="", late_comment=""):
    """Declare une etape. `inputs` = liste de (lot, quantite en unite de base du lot)."""
    errors = {}
    if step not in ProductionRun.Step.values:
        errors["step"] = ["Choisissez une étape de la liste."]
    if not inputs:
        errors["inputs"] = ["Ajoutez au moins un lot consommé."]
    if not output_article.is_active:
        errors["output_article"] = ["Cet article est désactivé."]
    if output_article.article_type == Article.Type.MATIERE and step != ProductionRun.Step.MURISSEMENT:
        errors["output_article"] = ["Une matière première ne se produit pas (sauf au mûrissement)."]
    if output_article.article_type == Article.Type.EMBALLAGE:
        errors["output_article"] = ["Un emballage ne se produit pas."]
    if equipment is not None and not equipment.is_active:
        errors["equipment"] = ["Cet équipement est désactivé."]
    lot_ids = [lot.id for lot, _ in inputs]
    if len(set(lot_ids)) != len(lot_ids):
        errors["inputs"] = ["Un même lot apparaît deux fois : regroupez les quantités."]
    if errors:
        raise ValidationError(errors)

    ended_at, late_reason_code, late_comment = lots.check_entry_time(ended_at, late_reason_code, late_comment,
                                                                     field="ended_at")
    started_at = started_at or ended_at
    if started_at > ended_at:
        raise ValidationError({"started_at": ["Le début doit précéder la fin."]})
    if equipment is not None and equipment.site_id:
        if site is not None and site.id != equipment.site_id:
            raise ValidationError({"equipment": ["Cet équipement est sur un autre site."]})
        site = equipment.site
    site = lots.default_site(site)

    output_base = lots.to_base_quantity(article=output_article, quantity=output_quantity,
                                        unit=output_unit or output_article.base_unit)
    locked = []
    for lot, qty in inputs:
        if qty is None or qty <= 0:
            raise ValidationError({"inputs": [f"Quantité consommée du lot {lot.code} : strictement positive."]})
        if qty != qty.quantize(lots.THOUSANDTH):
            raise ValidationError({"inputs": ["3 décimales au maximum."]})
        locked.append((Lot.objects.select_for_update().select_related("article").get(pk=lot.pk), qty))
    status = output_organic_status([lot for lot, _ in locked])

    mass_in = sum((qty for lot, qty in locked if counts_in_balance(lot, output_article)), Decimal("0"))
    if mass_in and output_base > mass_in:
        raise ValidationError({"output_quantity": [
            f"Quantité produite ({output_base} {output_article.base_unit}) supérieure à la matière consommée "
            f"({mass_in} {output_article.base_unit}) : vérifiez les pesées."
        ]})
    waste = waste_quantity or Decimal("0")
    if waste < 0:
        raise ValidationError({"waste_quantity": ["Quantité de déchets positive ou nulle."]})
    if waste:
        waste_code, waste_comment = lot_reasons.check(reasons.WASTE, waste_code, waste_comment, field="waste_code")
        if mass_in and output_base + waste > mass_in:
            raise ValidationError({"waste_quantity": ["Produit + déchets dépassent la matière consommée."]})
    else:
        waste_code, waste_comment = "", ""

    if not expiry_date and output_article.shelf_life_days:
        # DDM proposee depuis la duree de vie de l'article : une saisie de moins a l'atelier.
        expiry_date = timezone.localtime(ended_at).date() + datetime.timedelta(days=output_article.shelf_life_days)
        date_type = date_type or Lot.DateType.DDM
    output_lot = lots.create_lot(
        tenant_id=tenant_id, user=user, article=output_article, quantity=output_base,
        entry_type=Movement.Type.PRODUCTION, date_type=date_type or "", expiry_date=expiry_date,
        occurred_at=ended_at, organic_status=status, site=site, late_reason_code=late_reason_code,
        late_comment=late_comment,
    )
    run = ProductionRun.objects.create(
        tenant_id=tenant_id, step=step, equipment=equipment, site=site, output_lot=output_lot,
        input_quantity=mass_in, output_quantity=output_base, waste_quantity=waste, waste_code=waste_code,
        waste_comment=waste_comment, yield_min_pct=output_article.yield_min_pct,
        yield_max_pct=output_article.yield_max_pct, started_at=started_at, ended_at=ended_at, user=user,
        late_reason_code=late_reason_code, late_comment=late_comment,
    )
    for lot, qty in locked:
        movement = lots.record_exit(
            tenant_id=tenant_id, user=user, lot_id=lot.id, movement_type=Movement.Type.CONSOMMATION, quantity=qty,
            occurred_at=started_at, late_reason_code=late_reason_code, late_comment=late_comment,
        )
        ProductionInput.objects.create(tenant_id=tenant_id, run=run, lot=lot, quantity=qty, movement=movement)
        lots.link_lots(tenant_id=tenant_id, user=user, parent=lot, child=output_lot)

    record_audit(tenant_id=tenant_id, user=user, action="create", entity=run, new_values=_run_values(run))
    publish_event(tenant_id=tenant_id, event_type="production.declared",
                  payload={"run_id": str(run.id), "output_lot_id": str(output_lot.id), "step": step})
    deviation = yield_status(run)
    if deviation in ("bas", "haut"):
        publish_event(tenant_id=tenant_id, event_type="production.yield_deviation", payload={
            "run_id": str(run.id), "direction": deviation,
            "yield_pct": str((run.output_quantity * 100 / run.input_quantity).quantize(Decimal("0.01"))),
        })
    return run


# Equipements -------------------------------------------------------------------

EQUIPMENT_FIELDS = ["code", "name", "equipment_type", "is_active"]


def _equipment_values(e):
    values = {f: getattr(e, f) for f in EQUIPMENT_FIELDS}
    values["site_id"] = str(e.site_id) if e.site_id else None
    return values


def _check_equipment_code(code, exclude_id=None):
    qs = Equipment.objects.filter(code__iexact=code)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError({"code": [f"L'équipement {code} existe déjà."]})


@transaction.atomic
def create_equipment(*, tenant_id, user, code, name, equipment_type, site=None, is_active=True):
    code = code.strip()
    _check_equipment_code(code)
    equipment = Equipment.objects.create(tenant_id=tenant_id, code=code, name=name, equipment_type=equipment_type,
                                         site=site, is_active=is_active)
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=equipment,
                 new_values=_equipment_values(equipment))
    publish_event(tenant_id=tenant_id, event_type="equipment.created", payload={"equipment_id": str(equipment.id)})
    return equipment


@transaction.atomic
def update_equipment(*, tenant_id, user, equipment, **changes):
    old = _equipment_values(equipment)
    if "code" in changes:
        changes["code"] = changes["code"].strip()
        _check_equipment_code(changes["code"], exclude_id=equipment.pk)
    for field, value in changes.items():
        setattr(equipment, field, value)
    equipment.save()
    new = _equipment_values(equipment)
    if new != old:
        record_audit(tenant_id=tenant_id, user=user, action="update", entity=equipment, old_values=old, new_values=new)
        publish_event(tenant_id=tenant_id, event_type="equipment.updated", payload={"equipment_id": str(equipment.id)})
    return equipment
