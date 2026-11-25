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
