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
from lots.models import Lot, LotLink, Movement
from production import reasons
from production.models import (
    Equipment,
    ProductionInput,
    ProductionRun,
    ProductRoute,
    RouteArticle,
    RouteStep,
    RunCancellation,
    StepSetting,
)

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


def _active_steps():
    # Import local : selectors importe deja ce module (yield_status).
    from production.selectors import active_steps

    return active_steps()


def _route_steps_by_article():
    from production.selectors import route_steps_by_article

    return route_steps_by_article()


def _route_errors(step, inputs, output_article):
    """Etape hors du parcours du produit obtenu ou d'un lot consomme (emballages exclus)."""
    routes = _route_steps_by_article()
    if not routes or step not in ProductionRun.Step.values:
        return {}
    label = ProductionRun.Step(step).label
    errors = {}
    route = routes.get(output_article.id)
    if route and step not in route["steps"]:
        errors["step"] = [f"L'étape « {label} » ne fait pas partie du parcours « {route['route']} » "
                          f"du produit {output_article.code}."]
    for lot, _ in inputs:
        if lot.article.article_type == Article.Type.EMBALLAGE:
            continue
        route = routes.get(lot.article_id)
        if route and step not in route["steps"]:
            errors["inputs"] = [f"Le lot {lot.code} ({lot.article.code}) suit le parcours « {route['route']} », "
                                f"qui ne prévoit pas l'étape « {label} »."]
            break
    return errors


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
    elif step not in {s["code"] for s in _active_steps()}:
        errors["step"] = [f"L'étape « {ProductionRun.Step(step).label} » est désactivée pour votre entreprise."]
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
    if not errors:
        errors = _route_errors(step, inputs, output_article)
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
        locked.append((Lot.objects.select_for_update(of=("self",)).select_related("article", "site").get(pk=lot.pk), qty))
    if site is not None:
        elsewhere = [lot for lot, _ in locked if lot.site_id and lot.site_id != site.id]
        if elsewhere:
            lot = elsewhere[0]
            raise ValidationError({"inputs": [
                f"Le lot {lot.code} est à {lot.site.name}, pas à {site.name} : transférez-le d'abord."
            ]})
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


@transaction.atomic
def cancel_run(*, tenant_id, user, run_id, reason_code, comment=""):
    """Annule une declaration tant que le lot produit n'a servi a rien.

    Rien n'est efface : chaque consommation et la production recoivent un contre-mouvement, le lot produit est
    bloque (motif « déclaration annulée »), et une ligne d'annulation garde qui, quand et pourquoi.
    """
    reason_code, comment = lot_reasons.check(reasons.RUN_CANCEL, reason_code, comment)
    # La table des declarations est en insertion seule (pas de verrou FOR UPDATE possible) : on verrouille le lot
    # produit, ce qui suffit a eviter deux annulations simultanees (et l'unicite de RunCancellation.run).
    run = ProductionRun.objects.filter(pk=run_id).first()
    if run is None:
        raise ValidationError({"run": ["Déclaration introuvable."]})
    output = Lot.objects.select_for_update().get(pk=run.output_lot_id)
    if RunCancellation.objects.filter(run=run).exists():
        raise ValidationError({"run": ["Cette déclaration est déjà annulée."]})
    entry = output.movements.filter(movement_type=Movement.Type.PRODUCTION).first()
    used = output.movements.exclude(pk=entry.pk).exists() or LotLink.objects.filter(parent_lot=output).exists()
    if used:
        raise ValidationError({"run": [
            f"Le lot produit {output.code} a déjà servi (consommé, expédié ou ajusté) : "
            "annulez d'abord ce qui le suit."
        ]})
    lots.reverse_movement(tenant_id=tenant_id, user=user, movement_id=entry.id, reason_code=reason_code,
                          comment=comment)
    for production_input in run.inputs.select_related("movement"):
        lots.reverse_movement(tenant_id=tenant_id, user=user, movement_id=production_input.movement_id,
                              reason_code=reason_code, comment=comment)
    old = lots._lot_values(output)
    output.status, output.block_code = Lot.Status.BLOQUE, lot_reasons.RUN_CANCELLED
    output.block_reason = lot_reasons.text(lot_reasons.BLOCK_AUTO, lot_reasons.RUN_CANCELLED, "")
    output.save(update_fields=["status", "block_code", "block_reason", "updated_at"])
    record_audit(tenant_id=tenant_id, user=user, action="block", entity=output, old_values=old,
                 new_values=lots._lot_values(output))
    cancellation = RunCancellation.objects.create(
        tenant_id=tenant_id, run=run, reason_code=reason_code, comment=comment, user=user,
    )
    record_audit(tenant_id=tenant_id, user=user, action="cancel", entity=run, old_values=_run_values(run),
                 new_values={"reason_code": reason_code,
                             "reason": lot_reasons.text(reasons.RUN_CANCEL, reason_code, comment)})
    publish_event(tenant_id=tenant_id, event_type="production.cancelled",
                  payload={"run_id": str(run.id), "output_lot_id": str(output.id), "reason_code": reason_code})
    return cancellation


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


@transaction.atomic
def configure_steps(*, tenant_id, user, steps):
    """Active et ordonne les etapes de l'entreprise. `steps` = liste ordonnee de {"code", "is_active"}.

    Les etapes non citees sont desactivees et rangees apres, dans l'ordre du catalogue.
    Les declarations deja faites ne changent pas.
    """
    catalog = list(ProductionRun.Step.values)
    cited = [s["code"] for s in steps]
    if not steps:
        raise ValidationError({"steps": ["Choisissez au moins une étape."]})
    unknown = [c for c in cited if c not in catalog]
    if unknown:
        raise ValidationError({"steps": [f"Étape inconnue : {', '.join(unknown)}."]})
    if len(set(cited)) != len(cited):
        raise ValidationError({"steps": ["Une même étape apparaît deux fois."]})
    if not any(s["is_active"] for s in steps):
        raise ValidationError({"steps": ["Gardez au moins une étape active."]})

    wanted = {s["code"]: (bool(s["is_active"]), i) for i, s in enumerate(steps)}
    rest = [c for c in catalog if c not in wanted]
    for i, code in enumerate(rest):
        wanted[code] = (False, len(steps) + i)

    existing = {s.step: s for s in StepSetting.objects.select_for_update()}
    changed = False
    for code, (is_active, position) in wanted.items():
        setting = existing.get(code)
        new = {"step": code, "is_active": is_active, "position": position}
        if setting is None:
            setting = StepSetting.objects.create(tenant_id=tenant_id, **new)
            record_audit(tenant_id=tenant_id, user=user, action="create", entity=setting, new_values=new)
            changed = True
            continue
        old = {"step": code, "is_active": setting.is_active, "position": setting.position}
        if old != new:
            setting.is_active, setting.position = is_active, position
            setting.save(update_fields=["is_active", "position", "updated_at"])
            record_audit(tenant_id=tenant_id, user=user, action="update", entity=setting, old_values=old,
                         new_values=new)
            changed = True
    if changed:
        publish_event(tenant_id=tenant_id, event_type="production.steps_configured",
                      payload={"active": [c for c, (a, _) in sorted(wanted.items(), key=lambda x: x[1][1]) if a]})


def _clean_route(*, route_id, name, steps, articles):
    """Valide un parcours. `articles` = articles deja trouves (la RLS cache ceux d'un autre client)."""
    errors = {}
    name = (name or "").strip()
    if not name:
        errors["name"] = ["Donnez un nom au parcours."]
    elif ProductRoute.objects.filter(name__iexact=name).exclude(pk=route_id).exists():
        errors["name"] = ["Un parcours porte déjà ce nom."]
    active = {s["code"] for s in _active_steps()}
    if not steps:
        errors["steps"] = ["Choisissez au moins une étape."]
    elif any(c not in ProductionRun.Step.values for c in steps):
        errors["steps"] = ["Étape inconnue."]
    elif len(set(steps)) != len(steps):
        errors["steps"] = ["Une même étape apparaît deux fois."]
    elif any(c not in active for c in steps):
        off = [ProductionRun.Step(c).label for c in steps if c not in active]
        errors["steps"] = [f"Activez d'abord ces étapes pour l'entreprise : {', '.join(off)}."]
    if not articles:
        errors["articles"] = ["Rattachez au moins un article."]
    elif any(a.article_type == Article.Type.EMBALLAGE for a in articles):
        errors["articles"] = ["Un emballage ne suit pas de parcours."]
    else:
        taken = (RouteArticle.objects.filter(article__in=articles).exclude(route_id=route_id)
                 .select_related("article", "route").order_by("article__code").first())
        if taken is not None:
            errors["articles"] = [f"L'article {taken.article.code} est déjà dans le parcours « {taken.route.name} »."]
    if errors:
        raise ValidationError(errors)
    return name


def _route_values(route):
    return {
        "name": route.name, "is_active": route.is_active,
        "steps": sorted(route.steps.values_list("step", flat=True)),
        "articles": sorted(str(a) for a in route.articles.values_list("article_id", flat=True)),
    }


def _set_route_members(*, tenant_id, route, steps, articles):
    RouteStep.objects.filter(route=route).exclude(step__in=steps).delete()
    have = set(RouteStep.objects.filter(route=route).values_list("step", flat=True))
    RouteStep.objects.bulk_create([RouteStep(tenant_id=tenant_id, route=route, step=c) for c in steps if c not in have])
    ids = [a.id for a in articles]
    RouteArticle.objects.filter(route=route).exclude(article_id__in=ids).delete()
    have = set(RouteArticle.objects.filter(route=route).values_list("article_id", flat=True))
    RouteArticle.objects.bulk_create(
        [RouteArticle(tenant_id=tenant_id, route=route, article=a) for a in articles if a.id not in have]
    )


@transaction.atomic
def create_route(*, tenant_id, user, name, steps, articles, is_active=True):
    """Cree le parcours d'un produit : les etapes permises pour ses articles."""
    name = _clean_route(route_id=None, name=name, steps=steps, articles=articles)
    route = ProductRoute.objects.create(tenant_id=tenant_id, name=name, is_active=is_active)
    _set_route_members(tenant_id=tenant_id, route=route, steps=steps, articles=articles)
    new = _route_values(route)
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=route, new_values=new)
    publish_event(tenant_id=tenant_id, event_type="production.route_created",
                  payload={"route_id": str(route.id), "steps": new["steps"]})
    return route


@transaction.atomic
def update_route(*, tenant_id, user, route, name, steps, articles, is_active):
    """Remplace le nom, l'etat, les etapes et les articles d'un parcours. Les declarations faites ne changent pas."""
    route = ProductRoute.objects.select_for_update().get(pk=route.pk)
    name = _clean_route(route_id=route.id, name=name, steps=steps, articles=articles)
    old = _route_values(route)
    route.name, route.is_active = name, is_active
    route.save(update_fields=["name", "is_active", "updated_at"])
    _set_route_members(tenant_id=tenant_id, route=route, steps=steps, articles=articles)
    new = _route_values(route)
    if new != old:
        record_audit(tenant_id=tenant_id, user=user, action="update", entity=route, old_values=old, new_values=new)
        publish_event(tenant_id=tenant_id, event_type="production.route_updated",
                      payload={"route_id": str(route.id), "steps": new["steps"], "is_active": is_active})
    return route
