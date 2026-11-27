from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.services import record_audit
from events.services import publish_event
from core.tenancy import tenant_context
from tenants import jobs, selectors
from tenants.models import Site, Tenant, User


@transaction.atomic
def create_site(*, tenant_id, user, name, address=""):
    site = Site.objects.create(tenant_id=tenant_id, name=name, address=address)
    record_audit(
        tenant_id=tenant_id, user=user, action="create", entity=site,
        new_values={"name": name, "address": address},
    )
    publish_event(tenant_id=tenant_id, event_type="site.created", payload={"site_id": str(site.id)})
    return site


@transaction.atomic
def create_tenant_with_admin(*, tenant_name, username, password, email=""):
    """Cree une entreprise et son premier administrateur. Reserve a l'equipe plateforme."""
    tenant = Tenant.objects.create(name=tenant_name)
    with tenant_context(tenant.id):
        admin = User.objects.create_user(
            username=username, password=password, email=email, tenant=tenant, role=User.Role.ADMIN
        )
    return tenant, admin


def _user_values(u):
    """Valeurs tracees au journal. Jamais le mot de passe."""
    return {
        "username": u.username, "first_name": u.first_name, "last_name": u.last_name, "job_title": u.job_title,
        "job_title_other": u.job_title_other, "phone": u.phone, "email": u.email, "role": u.role,
        "manager": u.manager.username if u.manager_id else None, "is_active": u.is_active,
    }


def _check_admin(tenant_id, user):
    if user.role != User.Role.ADMIN or user.tenant_id != tenant_id:
        raise PermissionDenied("Seul un administrateur de l'entreprise gère les utilisateurs.")


def _check_password(password, target):
    try:
        validate_password(password, user=target)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from exc


def _check_job(job_title, job_title_other):
    if not job_title:
        return "", ""
    if job_title not in jobs.JOB_TITLES:
        raise ValidationError({"job_title": ["Choisissez un poste dans la liste."]})
    other = (job_title_other or "").strip()
    if job_title == jobs.OTHER and not other:
        raise ValidationError({"job_title_other": ["Précisez le poste « Autre »."]})
    return job_title, other if job_title == jobs.OTHER else ""


def _check_manager(tenant_id, target, manager):
    if manager is None:
        return
    if manager.tenant_id != tenant_id:
        raise ValidationError({"manager": ["Supérieur introuvable."]})
    if not manager.is_active:
        raise ValidationError({"manager": ["Ce supérieur est désactivé."]})
    # Pas de boucle : remonter la chaine du superieur ne doit jamais retomber sur la personne.
    seen, current = set(), manager
    while current is not None and current.pk not in seen:
        if target.pk and current.pk == target.pk:
            raise ValidationError({"manager": ["Une personne ne peut pas dépendre d'elle-même, même indirectement."]})
        seen.add(current.pk)
        current = current.manager


@transaction.atomic
def create_user(*, tenant_id, user, username, password, role, first_name="", last_name="", job_title="",
                job_title_other="", phone="", email="", manager=None):
    """Ajoute un utilisateur a l'entreprise de `user` (un administrateur) : ecran Utilisateurs et commande
    create_user."""
    _check_admin(tenant_id, user)
    if selectors.username_taken(username):
        raise ValidationError({"username": ["Cet identifiant est déjà pris."]})
    job_title, job_title_other = _check_job(job_title, job_title_other)
    new = User(username=username, tenant_id=tenant_id, role=role, first_name=first_name.strip(),
               last_name=last_name.strip(), job_title=job_title, job_title_other=job_title_other,
               phone=phone.strip(), email=email.strip())
    _check_password(password, new)
    _check_manager(tenant_id, new, manager)
    new.manager = manager
    new.set_password(password)
    new.save()
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=new, new_values=_user_values(new))
    publish_event(tenant_id=tenant_id, event_type="user.created", payload={"user_id": str(new.id), "role": role})
    return new


EDITABLE = ("first_name", "last_name", "job_title", "job_title_other", "phone", "email", "role", "manager",
            "is_active")


@transaction.atomic
def update_user(*, tenant_id, user, target, password=None, **changes):
    """Modifie la fiche, le role, le superieur ou l'etat d'un utilisateur. Admin seulement."""
    _check_admin(tenant_id, user)
    if target.tenant_id != tenant_id:
        raise ValidationError({"user": ["Utilisateur introuvable."]})
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValidationError({field: ["Champ non modifiable."] for field in unknown})
    if target.pk == user.pk and changes.get("is_active") is False:
        raise ValidationError({"is_active": ["Vous ne pouvez pas désactiver votre propre compte."]})
    if target.pk == user.pk and "role" in changes and changes["role"] != User.Role.ADMIN:
        raise ValidationError({"role": ["Vous ne pouvez pas retirer votre propre rôle d'administrateur."]})
    old = _user_values(target)
    if "job_title" in changes or "job_title_other" in changes:
        changes["job_title"], changes["job_title_other"] = _check_job(
            changes.get("job_title", target.job_title), changes.get("job_title_other", target.job_title_other)
        )
    if "manager" in changes:
        _check_manager(tenant_id, target, changes["manager"])
    for field, value in changes.items():
        setattr(target, field, value.strip() if isinstance(value, str) else value)
    if password:
        _check_password(password, target)
        target.set_password(password)
    target.save()
    new = _user_values(target)
    before = {k: v for k, v in old.items() if new[k] != v}
    after = {k: new[k] for k in before}
    if password:
        after["password"] = "(modifié)"
    if after:
        record_audit(tenant_id=tenant_id, user=user, action="update", entity=target, old_values=before or None,
                     new_values=after)
        publish_event(tenant_id=tenant_id, event_type="user.updated",
                      payload={"user_id": str(target.id), "fields": sorted(after)})
    return target


@transaction.atomic
def archive_tenant(*, tenant_id):
    """Met une entreprise hors service sans rien effacer (journal et mouvements en insertion seule).

    L'entreprise est renommee et desactivee. Ses comptes sont desactives (plus de connexion possible,
    sessions ouvertes comprises) et leurs identifiants recoivent un suffixe d'archive, pour liberer
    les identifiants. Chaque compte modifie est trace au journal de l'entreprise archivee.
    Reserve aux commandes de la plateforme (aujourd'hui : remise a zero de la demo).
    """
    tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
    stamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    old_name = tenant.name
    tenant.name = f"{old_name} [archivée le {timezone.localtime():%d/%m/%Y à %H:%M}]"[:200]
    tenant.is_active = False
    tenant.save(update_fields=["name", "is_active"])
    with tenant_context(tenant.id):
        for account in User.objects.filter(tenant_id=tenant.id).order_by("username"):
            old = _user_values(account)
            account.username = f"{account.username}.archive{stamp}"
            account.is_active = False
            account.save(update_fields=["username", "is_active"])
            record_audit(tenant_id=tenant.id, user=None, action="update", entity=account, old_values=old,
                         new_values=_user_values(account))
        publish_event(tenant_id=tenant.id, event_type="tenant.archived",
                      payload={"tenant_id": str(tenant.id), "name": old_name})
    return tenant
