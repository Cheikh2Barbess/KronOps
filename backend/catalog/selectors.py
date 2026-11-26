"""Lectures du referentiel. Pas de filtre tenant ici : la RLS de PostgreSQL le fait."""

from django.db.models import Prefetch
from django.db.models.functions import Lower
from django.http import Http404

from catalog.models import Allergen, Article, ArticleAllergen, Partner, UnitConversion

# Liste d'allergenes utilisee en phase 1 pour toutes les entreprises.
DEFAULT_REGULATION = "UE_1169_2011"


def allergen_list(*, regulation=DEFAULT_REGULATION):
    return Allergen.objects.filter(regulation=regulation).order_by("order")


def allergen_codes(*, regulation=DEFAULT_REGULATION):
    return list(allergen_list(regulation=regulation).values_list("code", flat=True))


def articles(*, article_type=None, active=None):
    qs = Article.objects.prefetch_related(
        Prefetch("allergen_rows", queryset=ArticleAllergen.objects.select_related("allergen"))
    ).order_by("code")
    if article_type:
        qs = qs.filter(article_type=article_type)
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs


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


def partners(*, role=None, active=None):
    qs = Partner.objects.order_by("name")
    if role == "supplier":
        qs = qs.filter(is_supplier=True)
    elif role == "customer":
        qs = qs.filter(is_customer=True)
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs


def partner_or_404(*, partner_id):
    partner = Partner.objects.filter(pk=partner_id).first()
    if partner is None:
        raise Http404
    return partner


def existing_partner_names(names):
    lowered = {n.lower() for n in names}
    return set(Partner.objects.annotate(lname=Lower("name")).filter(lname__in=lowered).values_list("lname", flat=True))
