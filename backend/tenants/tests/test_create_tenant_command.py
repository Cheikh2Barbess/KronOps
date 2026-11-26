from django.core.management import call_command

from core.tenancy import tenant_context
from tenants.models import Tenant, User


def test_create_tenant_command():
    call_command("create_tenant", name="Biscuiterie Test", admin="patron", password="un-mot-de-passe-solide-42")
    tenant = Tenant.objects.get(name="Biscuiterie Test")
    with tenant_context(tenant.id):  # la RLS cache les comptes hors contexte d'entreprise
        user = User.objects.get(username="patron")
    assert user.tenant == tenant
    assert user.role == User.Role.ADMIN
