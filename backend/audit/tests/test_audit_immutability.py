"""Le journal d'audit est en insertion seule. La BASE doit refuser toute modification,
quel que soit le code Python qui essaie."""

import pytest
from django.db import DatabaseError, connection, transaction

from audit.models import AuditLog
from core.tenancy import tenant_context
from tenants.services import create_site


@pytest.fixture
def audit_entry(tenant_a, admin_a):
    with tenant_context(tenant_a.id):
        create_site(tenant_id=tenant_a.id, user=admin_a, name="Usine")
        return AuditLog.objects.get(entity_type="tenants.site")


def test_business_action_writes_audit(audit_entry, admin_a):
    assert audit_entry.action == "create"
    assert audit_entry.user_id == admin_a.id
    assert audit_entry.new_values == {"name": "Usine", "address": ""}


def test_app_role_cannot_update_audit(audit_entry, tenant_a):
    with pytest.raises(DatabaseError):
        with tenant_context(tenant_a.id):
            AuditLog.objects.filter(pk=audit_entry.pk).update(action="falsifie")


def test_app_role_cannot_delete_audit(audit_entry, tenant_a):
    with pytest.raises(DatabaseError):
        with tenant_context(tenant_a.id):
            AuditLog.objects.filter(pk=audit_entry.pk).delete()


def test_even_table_owner_cannot_update_or_delete_audit(audit_entry, tenant_a):
    """Le trigger bloque meme le role proprietaire (celui des migrations)."""
    for statement in ("UPDATE audit_auditlog SET action = 'x'", "DELETE FROM audit_auditlog"):
        with pytest.raises(DatabaseError, match="insertion seule"):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE")
                    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_a.id)])
                    cursor.execute(statement)


def test_owner_cannot_truncate_audit():
    # Sans ligne inseree dans ce test : PostgreSQL refuse TRUNCATE si des contraintes
    # differees sont en attente, ce qui masquerait le trigger.
    with pytest.raises(DatabaseError, match="insertion seule"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
                cursor.execute("TRUNCATE audit_auditlog")
