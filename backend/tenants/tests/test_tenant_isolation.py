"""Isolation entre clients : la base elle-meme doit empecher A de voir les donnees de B."""

import pytest
from django.db import DatabaseError, transaction

from core.tenancy import TenantContextError, set_db_tenant, tenant_context
from tenants.models import Site
from tenants.selectors import users_of_tenant


def test_site_of_other_tenant_is_invisible_through_api(client_a, site_of_tenant_b):
    response = client_a.get(f"/api/v1/sites/{site_of_tenant_b.id}/")
    assert response.status_code == 404


def test_site_list_only_shows_own_tenant(client_a, site_of_tenant_a, site_of_tenant_b):
    response = client_a.get("/api/v1/sites/")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [str(site_of_tenant_a.id)]


def test_database_hides_other_tenant_rows_even_without_filter(tenant_a, site_of_tenant_a, site_of_tenant_b):
    with tenant_context(tenant_a.id):
        assert list(Site.objects.all()) == [site_of_tenant_a]


def test_no_tenant_context_means_no_rows(site_of_tenant_a):
    with transaction.atomic():
        assert Site.objects.count() == 0


def test_cannot_write_a_row_for_another_tenant(tenant_a, tenant_b):
    with pytest.raises(DatabaseError):
        with tenant_context(tenant_a.id):
            Site.objects.create(tenant=tenant_b, name="Intrusion")


def test_tenant_id_in_request_body_is_ignored(client_a, tenant_a, tenant_b):
    response = client_a.post("/api/v1/sites/", {"name": "Nouveau", "tenant": str(tenant_b.id)}, format="json")
    assert response.status_code == 201
    with tenant_context(tenant_a.id):
        assert Site.objects.get(pk=response.json()["id"]).tenant_id == tenant_a.id


def test_set_db_tenant_refuses_outside_transaction(tenant_a, django_db_blocker):
    # Hors transaction, le reglage serait perdu aussitot : on doit refuser.
    from django.db import connection

    previous = connection.in_atomic_block
    connection.in_atomic_block = False
    try:
        with pytest.raises(TenantContextError):
            set_db_tenant(tenant_a.id)
    finally:
        connection.in_atomic_block = previous


def test_users_selector_filters_by_tenant(admin_a, admin_b):
    assert list(users_of_tenant(tenant_id=admin_a.tenant_id)) == [admin_a]
