import pytest
from django.core.management import CommandError, call_command

from audit.models import AuditLog
from core.tenancy import tenant_context
from tenants.models import User

PASSWORD = "un-mot-de-passe-solide-42"


def test_admin_adds_a_quality_user_in_own_company(admin_a, tenant_a):
    call_command("create_user", admin=admin_a.username, username="marie", role="qualite", password=PASSWORD)
    with tenant_context(tenant_a.id):
        marie = User.objects.get(username="marie")
        assert (marie.tenant_id, marie.role) == (tenant_a.id, "qualite")
        assert AuditLog.objects.filter(entity_id=marie.id, action="create").exists()


def test_refuses_unknown_admin_duplicate_and_bad_role(admin_a, tenant_a):
    with pytest.raises(CommandError, match="Aucun administrateur"):
        call_command("create_user", admin="personne", username="x", role="qualite", password=PASSWORD)
    with pytest.raises(CommandError, match="existe deja"):
        call_command("create_user", admin=admin_a.username, username=admin_a.username, role="qualite",
                     password=PASSWORD)
    with pytest.raises(CommandError):
        call_command("create_user", admin=admin_a.username, username="y", role="chef", password=PASSWORD)
