from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from core.models import TenantModel, UUIDModel


class Allergen(UUIDModel):
    """Liste de reference des allergenes, commune a toutes les entreprises (pas de tenant_id, pas de RLS).

    Remplie par migration. Le role applicatif peut seulement la LIRE (voir la migration 0002).
    Phase 1 : liste de l'annexe II du reglement (UE) 1169/2011, 14 allergenes. Une liste propre
    a un pays s'ajoutera avec une autre valeur de `regulation`.
    """

    regulation = models.CharField("réglementation", max_length=30)
    code = models.CharField(max_length=40)
    name = models.CharField("nom", max_length=200)
    order = models.PositiveSmallIntegerField("ordre")

    class Meta:
        verbose_name = "allergène"
        ordering = ["regulation", "order"]
        constraints = [models.UniqueConstraint(fields=["regulation", "code"], name="allergen_unique_code")]

    def __str__(self):
        return self.name


class Article(TenantModel):
    """Matiere, emballage, semi-fini ou produit fini.

    Stock et mouvements sont toujours exprimes dans `base_unit`, qui ne change plus apres creation.
    """

    class Type(models.TextChoices):
        MATIERE = "matiere", "Matière première"
        EMBALLAGE = "emballage", "Emballage"
        SEMI_FINI = "semi_fini", "Semi-fini"
        FINI = "fini", "Produit fini"

    class Unit(models.TextChoices):
        KG = "kg", "kg"
        L = "l", "L"
        UNITE = "unite", "unité"

    class Storage(models.TextChoices):
        AMBIANT = "ambiant", "Ambiant"
        REFRIGERE = "refrigere", "Réfrigéré"
        CONGELE = "congele", "Congelé"

    code = models.CharField(max_length=50)
    name = models.CharField("nom", max_length=200)
    article_type = models.CharField("type", max_length=20, choices=Type.choices)
    base_unit = models.CharField("unité de base", max_length=10, choices=Unit.choices)
    shelf_life_days = models.PositiveIntegerField(
        "durée de vie (jours)", null=True, blank=True, validators=[MinValueValidator(1)]
    )
    storage = models.CharField("conservation", max_length=20, choices=Storage.choices, blank=True)
    allergens_declared = models.BooleanField("allergènes déclarés", default=False)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "article"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="article_unique_code_per_tenant"),
            models.CheckConstraint(
                condition=Q(shelf_life_days__isnull=True) | Q(shelf_life_days__gte=1),
                name="article_shelf_life_positive",
            ),
            # Une matiere premiere n'existe jamais sans declaration d'allergenes.
            models.CheckConstraint(
                condition=~Q(article_type="matiere") | Q(allergens_declared=True),
                name="article_raw_material_allergens_declared",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "article_type", "code"])]

    def __str__(self):
        return f"{self.code} {self.name}"


class ArticleAllergen(TenantModel):
    """Presence d'un allergene dans un article. « absent » est declare, jamais deduit d'une ligne manquante."""

    class Presence(models.TextChoices):
        CONTIENT = "contient", "Contient"
        PEUT_CONTENIR = "peut_contenir", "Peut contenir"
        ABSENT = "absent", "Absent"

    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="allergen_rows")
    allergen = models.ForeignKey(Allergen, on_delete=models.PROTECT, related_name="+")
    presence = models.CharField("présence", max_length=20, choices=Presence.choices)

    class Meta:
        verbose_name = "allergène d'un article"
        constraints = [
            models.UniqueConstraint(fields=["article", "allergen"], name="article_allergen_unique"),
        ]
        # Filtre « articles qui contiennent tel allergene ».
        indexes = [models.Index(fields=["allergen", "presence"], name="article_allergen_presence")]


class UnitConversion(TenantModel):
    """1 `unit_name` = `factor` unites de base de l'article (ex. 1 sac = 25 kg)."""

    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="conversions")
    unit_name = models.CharField("unité", max_length=30)
    factor = models.DecimalField("facteur", max_digits=18, decimal_places=6)

    class Meta:
        verbose_name = "conversion d'unité"
        constraints = [
            models.UniqueConstraint("article", Lower("unit_name"), name="conversion_unique_unit_per_article"),
            models.CheckConstraint(condition=Q(factor__gt=0), name="conversion_factor_positive"),
        ]


class Partner(TenantModel):
    """Fournisseur et/ou client. Nom et adresse obligatoires (identification amont et aval)."""

    name = models.CharField("nom", max_length=200)
    is_supplier = models.BooleanField("fournisseur", default=False)
    is_customer = models.BooleanField("client", default=False)
    address = models.TextField("adresse")
    # Ville a part de l'adresse : sert au filtre (ex. tous les clients d'Abidjan).
    city = models.CharField("ville", max_length=100, blank=True, default="")
    contact_name = models.CharField("contact", max_length=200, blank=True)
    phone = models.CharField("téléphone", max_length=50, blank=True)
    email = models.EmailField("e-mail", blank=True)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "partenaire"
        constraints = [
            models.UniqueConstraint("tenant", Lower("name"), name="partner_unique_name_per_tenant"),
            models.CheckConstraint(condition=Q(is_supplier=True) | Q(is_customer=True), name="partner_has_role"),
        ]
        indexes = [
            models.Index(fields=["tenant", "name"]),
            models.Index(F("tenant"), Lower("city"), name="partner_tenant_city"),
        ]

    def __str__(self):
        return self.name
