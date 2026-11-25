import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q

from core.models import TenantModel, UUIDModel


class Tenant(UUIDModel):
    """Une entreprise cliente. C'est le registre des clients : pas de RLS sur cette table.

    Elle n'est lue que par le code du socle (connexion, administration plateforme),
    jamais exposee en liste par l'API.
    """

    class Plan(models.TextChoices):
        ESSENTIEL = "essentiel", "Essentiel"
        QUALITE = "qualite", "Qualité"
        PERFORMANCE = "performance", "Performance"

    name = models.CharField("nom", max_length=200)
    country = models.CharField("pays (code ISO 3166-1 alpha-2)", max_length=2, default="CI")
    currency = models.CharField("devise (code ISO 4217)", max_length=3, default="XOF")
    language = models.CharField("langue", max_length=10, default="fr")
    sanitary_approval_number = models.CharField("n° d'agrément sanitaire", max_length=100, blank=True)
    plan = models.CharField("offre", max_length=20, choices=Plan.choices, default=Plan.ESSENTIEL)
    is_active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "entreprise"

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Compte utilisateur.

    Exception assumee a la regle RLS : la table des utilisateurs n'a PAS de RLS, car la
    connexion doit retrouver l'utilisateur avant de connaitre son entreprise. Consequence :
    toute lecture d'utilisateurs dans l'API DOIT filtrer par tenant_id dans le code
    (voir tenants/selectors.py), et un test le verifie.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        QUALITE = "qualite", "Qualité"
        PRODUCTION = "production", "Production"
        OPERATEUR = "operateur", "Opérateur"
        LECTURE = "lecture", "Lecture"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.LECTURE)

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            # Seul un superutilisateur de la plateforme (equipe KronOps) peut n'appartenir a aucune entreprise.
            models.CheckConstraint(
                condition=Q(tenant__isnull=False) | Q(is_superuser=True),
                name="user_has_tenant_unless_superuser",
            )
        ]


class Site(TenantModel):
    """Site de production. Un seul site en v1, mais la table existe des le depart."""

    name = models.CharField("nom", max_length=200)
    address = models.TextField("adresse", blank=True)

    class Meta:
        verbose_name = "site"
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="site_unique_name_per_tenant")]
        indexes = [models.Index(fields=["tenant", "name"])]

    def __str__(self):
        return self.name
