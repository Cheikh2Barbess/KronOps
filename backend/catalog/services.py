"""Regles metier du referentiel (US-02). Toute ecriture passe par ici."""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from audit.services import record_audit
from catalog import selectors
from catalog.models import Article, ArticleAllergen, Partner, UnitConversion
from events.services import publish_event

ARTICLE_FIELDS = ["code", "name", "article_type", "base_unit", "shelf_life_days", "storage", "is_active"]
PARTNER_FIELDS = ["name", "is_supplier", "is_customer", "address", "contact_name", "phone", "email", "is_active"]


# Allergenes ---------------------------------------------------------------


def check_allergen_declaration(*, article_type, allergens):
    """Verifie la declaration d'allergenes. Renvoie le dictionnaire {code: presence} ou None.

    Regle PRD : une matiere premiere porte TOUS les allergenes de la liste, chacun declare
    (contient, peut contenir, absent). « absent » n'est jamais deduit d'une ligne manquante.
    """
    if allergens is None:
        if article_type == Article.Type.MATIERE:
            raise ValidationError({"allergens": ["Déclaration des allergènes obligatoire pour une matière première."]})
        return None
    codes = selectors.allergen_codes()
    unknown = sorted(set(allergens) - set(codes))
    missing = [c for c in codes if c not in allergens]
    errors = []
    if unknown:
        errors.append(f"Allergènes inconnus : {', '.join(unknown)}.")
    if missing:
        errors.append(f"Allergènes non déclarés : {', '.join(missing)}.")
    bad = sorted(c for c, p in allergens.items() if p not in ArticleAllergen.Presence.values)
    if bad:
        errors.append(f"Présence invalide pour : {', '.join(bad)} (contient, peut_contenir ou absent).")
    if errors:
        raise ValidationError({"allergens": errors})
    return {c: allergens[c] for c in codes}


def _allergen_map(article):
    return {row.allergen.code: row.presence for row in article.allergen_rows.select_related("allergen")}


def _write_allergens(*, tenant_id, article, allergens):
    by_code = {a.code: a for a in selectors.allergen_list()}
    ArticleAllergen.objects.filter(article=article).delete()
    ArticleAllergen.objects.bulk_create(
        ArticleAllergen(tenant_id=tenant_id, article=article, allergen=by_code[code], presence=presence)
        for code, presence in allergens.items()
    )


# Articles -----------------------------------------------------------------


def article_snapshot(article):
    values = {f: getattr(article, f) for f in ARTICLE_FIELDS}
    values["allergens"] = _allergen_map(article) if article.allergens_declared else None
    return values


def _check_code_free(code, exclude_id=None):
    qs = Article.objects.filter(code=code)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError({"code": [f"Le code {code} existe déjà."]})


@transaction.atomic
def create_article(*, tenant_id, user, allergens=None, audit_action="create", **fields):
    allergens = check_allergen_declaration(article_type=fields.get("article_type"), allergens=allergens)
    _check_code_free(fields["code"])
    article = Article.objects.create(tenant_id=tenant_id, allergens_declared=allergens is not None, **fields)
    if allergens is not None:
        _write_allergens(tenant_id=tenant_id, article=article, allergens=allergens)
    record_audit(
        tenant_id=tenant_id, user=user, action=audit_action, entity=article, new_values=article_snapshot(article)
    )
    publish_event(
        tenant_id=tenant_id, event_type="article.created", payload={"article_id": str(article.id), "code": article.code}
    )
    return article


@transaction.atomic
def update_article(*, tenant_id, user, article, allergens=None, **changes):
    if "base_unit" in changes and changes["base_unit"] != article.base_unit:
        # Stock et mouvements sont stockes dans l'unite de base : la changer fausserait l'historique.
        raise ValidationError({"base_unit": ["L'unité de base ne peut pas être modifiée après la création."]})
    changes.pop("base_unit", None)
    if "code" in changes:
        _check_code_free(changes["code"], exclude_id=article.pk)

    old = article_snapshot(article)
    new_type = changes.get("article_type", article.article_type)
    if allergens is not None:
        allergens = check_allergen_declaration(article_type=new_type, allergens=allergens)
    elif new_type == Article.Type.MATIERE and not article.allergens_declared:
        check_allergen_declaration(article_type=new_type, allergens=None)  # leve l'erreur

    for field, value in changes.items():
        setattr(article, field, value)
    if allergens is not None:
        article.allergens_declared = True
    article.save()
    if allergens is not None:
        _write_allergens(tenant_id=tenant_id, article=article, allergens=allergens)

    new = article_snapshot(article)
    if new != old:
        record_audit(tenant_id=tenant_id, user=user, action="update", entity=article, old_values=old, new_values=new)
        publish_event(
            tenant_id=tenant_id,
            event_type="article.updated",
            payload={"article_id": str(article.id), "fields": sorted(k for k in new if new[k] != old[k])},
        )
    return article


@transaction.atomic
def import_articles(*, tenant_id, user, rows):
    """Cree tous les articles d'un fichier deja valide. Tout ou rien (une seule transaction)."""
    created = [create_article(tenant_id=tenant_id, user=user, audit_action="import", **row) for row in rows]
    publish_event(tenant_id=tenant_id, event_type="articles.imported", payload={"count": len(created)})
    return created


# Conversions d'unites -----------------------------------------------------


@transaction.atomic
def create_conversion(*, tenant_id, user, article, unit_name, factor):
    unit_name = unit_name.strip()
    if unit_name.lower() in {u.lower() for u in Article.Unit.values} | {"unité", "litre", "kilo"}:
        # Pas de conversion entre unites de base (kg <-> L : densite non geree).
        raise ValidationError({"unit_name": ["Choisissez un conditionnement (sac, carton...), pas une unité de base."]})
    if selectors.conversions_of(article=article).filter(unit_name__iexact=unit_name).exists():
        raise ValidationError({"unit_name": [f"La conversion « {unit_name} » existe déjà pour cet article."]})
    conversion = UnitConversion.objects.create(tenant_id=tenant_id, article=article, unit_name=unit_name, factor=factor)
    record_audit(
        tenant_id=tenant_id, user=user, action="create", entity=conversion,
        new_values={"article_id": str(article.id), "unit_name": unit_name, "factor": str(factor)},
    )
    publish_event(
        tenant_id=tenant_id, event_type="unit_conversion.created",
        payload={"conversion_id": str(conversion.id), "article_id": str(article.id)},
    )
    return conversion


# Partenaires --------------------------------------------------------------


def partner_snapshot(partner):
    return {f: getattr(partner, f) for f in PARTNER_FIELDS}


def _check_partner_rules(*, name, is_supplier, is_customer, exclude_id=None):
    if not (is_supplier or is_customer):
        raise ValidationError({"non_field_errors": ["Un partenaire est fournisseur, client, ou les deux."]})
    qs = Partner.objects.filter(name__iexact=name)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError({"name": [f"Le partenaire « {name} » existe déjà."]})


@transaction.atomic
def create_partner(*, tenant_id, user, audit_action="create", **fields):
    _check_partner_rules(
        name=fields["name"], is_supplier=fields.get("is_supplier", False), is_customer=fields.get("is_customer", False)
    )
    partner = Partner.objects.create(tenant_id=tenant_id, **fields)
    record_audit(
        tenant_id=tenant_id, user=user, action=audit_action, entity=partner, new_values=partner_snapshot(partner)
    )
    publish_event(tenant_id=tenant_id, event_type="partner.created", payload={"partner_id": str(partner.id)})
    return partner


@transaction.atomic
def update_partner(*, tenant_id, user, partner, **changes):
    old = partner_snapshot(partner)
    merged = {**old, **changes}
    _check_partner_rules(
        name=merged["name"], is_supplier=merged["is_supplier"], is_customer=merged["is_customer"],
        exclude_id=partner.pk,
    )
    for field, value in changes.items():
        setattr(partner, field, value)
    partner.save()
    new = partner_snapshot(partner)
    if new != old:
        record_audit(tenant_id=tenant_id, user=user, action="update", entity=partner, old_values=old, new_values=new)
        publish_event(tenant_id=tenant_id, event_type="partner.updated", payload={"partner_id": str(partner.id)})
    return partner


@transaction.atomic
def import_partners(*, tenant_id, user, rows):
    created = [create_partner(tenant_id=tenant_id, user=user, audit_action="import", **row) for row in rows]
    publish_event(tenant_id=tenant_id, event_type="partners.imported", payload={"count": len(created)})
    return created
