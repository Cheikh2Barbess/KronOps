import pytest
from django.db import transaction

from core.tenancy import tenant_context
from events.models import OutboxEvent
from events.services import OutsideTransactionError, publish_event
from tenants.services import create_site


def test_business_action_writes_event_in_same_transaction(tenant_a, admin_a):
    with tenant_context(tenant_a.id):
        site = create_site(tenant_id=tenant_a.id, user=admin_a, name="Usine")
        event = OutboxEvent.objects.get(event_type="site.created")
    assert event.payload == {"site_id": str(site.id)}
    assert event.processed_at is None


def test_event_disappears_when_action_fails(tenant_a, admin_a):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with tenant_context(tenant_a.id):
            create_site(tenant_id=tenant_a.id, user=admin_a, name="Usine")
            raise Boom
    with tenant_context(tenant_a.id):
        assert OutboxEvent.objects.count() == 0


def test_publish_event_refuses_outside_transaction(tenant_a):
    from django.db import connection

    previous = connection.in_atomic_block
    connection.in_atomic_block = False
    try:
        with pytest.raises(OutsideTransactionError):
            publish_event(tenant_id=tenant_a.id, event_type="x", payload={})
    finally:
        connection.in_atomic_block = previous
