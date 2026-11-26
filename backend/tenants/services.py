from django.db import transaction

from audit.services import record_audit
from events.services import publish_event
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
    admin = User.objects.create_user(
        username=username, password=password, email=email, tenant=tenant, role=User.Role.ADMIN
    )
    return tenant, admin


@transaction.atomic
def create_user(*, tenant_id, user, username, password, role):
    """Ajoute un utilisateur a l'entreprise de `user` (un administrateur). En attendant l'ecran de gestion
    des utilisateurs (US-01), sert a la commande create_user."""
    if user.role != User.Role.ADMIN or user.tenant_id != tenant_id:
        raise ValueError("Seul un administrateur de l'entreprise peut ajouter un utilisateur.")
    new = User.objects.create_user(username=username, password=password, tenant_id=tenant_id, role=role)
    record_audit(tenant_id=tenant_id, user=user, action="create", entity=new,
                 new_values={"username": username, "role": role})
    publish_event(tenant_id=tenant_id, event_type="user.created", payload={"user_id": str(new.id), "role": role})
    return new
