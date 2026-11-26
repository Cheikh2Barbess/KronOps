"""Lectures du referentiel. Pas de filtre tenant ici : la RLS de PostgreSQL le fait."""

from django.db.models import Count, Exists, Min, OuterRef, Prefetch, Q
from django.db.models.functions import Lower
from django.http import Http404

from catalog.models import Allergen, Article, ArticleAllergen, Partner, UnitConversion

# Liste d'allergenes utilisee en phase 1 pour toutes les entreprises.
DEFAULT_REGULATION = "UE_1169_2011"


def allergen_list(*, regulation=DEFAULT_REGULATION):
    return Allergen.objects.filter(regulation=regulation).order_by("order")


def allergen_codes(*, regulation=DEFAULT_REGULATION):
    return list(allergen_list(regulation=regulation).values_list("code", flat=True))


def articles(*, q=None, article_type=None, storage=None, active=None, allergen=None, presence="present",
             allergen_free=None, has_allergen=None):
    """Liste filtree. Une liste de valeurs = OU, des filtres differents = ET.

    `article_type` et `storage` acceptent une valeur ou une liste.
    """
    qs = Article.objects.prefetch_related(
        Prefetch("allergen_rows", queryset=ArticleAllergen.objects.select_related("allergen"))
    ).order_by("code")
    if q:
        qs = qs.filter(Q(code__unaccent__icontains=q) | Q(name__unaccent__icontains=q))
    if article_type:
        qs = qs.filter(article_type__in=_as_list(article_type))
    if storage:
        qs = qs.filter(storage__in=_as_list(storage))
    if active is not None:
        qs = qs.filter(is_active=active)
    present = [ArticleAllergen.Presence.CONTIENT, ArticleAllergen.Presence.PEUT_CONTENIR]
    if allergen:
        wanted = present if presence == "present" else [presence]
        qs = qs.filter(Exists(ArticleAllergen.objects.filter(
            article=OuterRef("pk"), allergen__code__in=allergen, presence__in=wanted)))
    if allergen_free:
        # « Sans » ne vaut que pour un article declare : un article non declare est inconnu.
        qs = qs.filter(allergens_declared=True).exclude(Exists(ArticleAllergen.objects.filter(
            article=OuterRef("pk"), allergen__code__in=allergen_free, presence__in=present)))
    if has_allergen is not None:
        any_present = Exists(ArticleAllergen.objects.filter(article=OuterRef("pk"), presence__in=present))
        qs = qs.filter(any_present) if has_allergen else qs.filter(allergens_declared=True).exclude(any_present)
    return qs


def _as_list(value):
    return value if isinstance(value, (list, tuple, set)) else [value]


def article_or_404(*, article_id):
    # Inexistant OU appartenant a un autre client : meme reponse 404.
    article = articles().filter(pk=article_id).first()
    if article is None:
        raise Http404
    return article


def existing_article_codes(codes):
    return set(Article.objects.filter(code__in=codes).values_list("code", flat=True))


def conversions_of(*, article):
    return UnitConversion.objects.filter(article=article).order_by("unit_name")


def partners(*, q=None, role=None, city=None, active=None):
    qs = Partner.objects.order_by("name")
    if q:
        qs = qs.filter(
            Q(name__unaccent__icontains=q) | Q(contact_name__unaccent__icontains=q)
            | Q(address__unaccent__icontains=q) | Q(city__unaccent__icontains=q)
        )
    if role == "supplier":
        qs = qs.filter(is_supplier=True)
    elif role == "customer":
        qs = qs.filter(is_customer=True)
    elif role == "both":
        qs = qs.filter(is_supplier=True, is_customer=True)
    if city:
        qs = qs.annotate(lcity=Lower("city")).filter(lcity__in=[c.lower() for c in _as_list(city)])
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs


def partner_cities():
    """Villes deja saisies, regroupees sans tenir compte des majuscules, avec le nombre de partenaires."""
    return (
        Partner.objects.exclude(city="").annotate(lcity=Lower("city")).values("lcity")
        .annotate(city=Min("city"), count=Count("id")).order_by("lcity")
    )


def partner_or_404(*, partner_id):
    partner = Partner.objects.filter(pk=partner_id).first()
    if partner is None:
        raise Http404
    return partner


def existing_partner_names(names):
    lowered = {n.lower() for n in names}
    return set(Partner.objects.annotate(lname=Lower("name")).filter(lname__in=lowered).values_list("lname", flat=True))
