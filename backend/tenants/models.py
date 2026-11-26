import uuid

from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import AbstractUser, UserManager
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


class TenantUserManager(UserManager):
    def get_by_natural_key(self, username):
        """Connexion (et createsuperuser) : l'entreprise n'est pas encore connue, la RLS cacherait
        le compte. On passe par la fonction SQL auth_user_by_username (migration tenants/0003)."""
        found = list(self.raw("SELECT * FROM auth_user_by_username(%s)", [username]))
        if not found:
            raise self.model.DoesNotExist
        return found[0]


class User(AbstractUser):
    """Compte utilisateur.

    Table protegee par la RLS comme les autres (migration tenants/0003) : la base ne montre que
    les comptes de l'entreprise courante. La connexion et la session, qui ne connaissent pas
    encore l'entreprise, passent par les fonctions SQL auth_* (voir tenants/auth.py).
    Les selecteurs (tenants/selectors.py) gardent quand meme un filtre tenant_id explicite.
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
    # Fiche (US-01, decision du 26/11/2026). Poste dans une liste fermee (tenants/jobs.py).
    job_title = models.CharField("poste", max_length=40, blank=True)
    job_title_other = models.CharField("poste (précision)", max_length=100, blank=True)
    phone = models.CharField("téléphone", max_length=30, blank=True)
    manager = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reports", verbose_name="supérieur"
    )

    objects = TenantUserManager()

    def check_password(self, raw_password):
        """Comme Django, mais le renforcement automatique du hachage (apres une mise a jour de
        Django) s'ecrit dans le contexte du compte, sinon la RLS refuserait l'ecriture."""
        from core.tenancy import account_context

        def setter(raw):
            self.set_password(raw)
            self._password = None
            with account_context(self):
                self.save(update_fields=["password"])

        return check_password(raw_password, self.password, setter)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            # Seul un superutilisateur de la plateforme (equipe Tracalys) peut n'appartenir a aucune entreprise.
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
