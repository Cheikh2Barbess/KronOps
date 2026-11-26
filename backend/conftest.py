"""Fixtures communes des tests.

Les tests tournent avec le role PROPRIETAIRE (il cree la base de test), mais chaque test
bascule sur le role APPLICATIF (SET LOCAL ROLE), pour verifier ce que fera vraiment
l'application en production : RLS active, droits retires sur les tables en insertion seule.
"""

import pytest
from django.conf import settings
from django.db import connection
from rest_framework.test import APIClient

from core.tenancy import tenant_context
from tenants.models import Site, Tenant, User

PASSWORD = "mot-de-passe-de-test-123"


@pytest.fixture(autouse=True)
def as_app_role(db):
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL ROLE {settings.DB_APP_ROLE}")
    yield


@pytest.fixture
def tenant_a():
    return Tenant.objects.create(name="Entreprise A")


@pytest.fixture
def tenant_b():
    return Tenant.objects.create(name="Entreprise B")


def make_user(tenant, username, role=User.Role.ADMIN):
    # La table des utilisateurs est protegee par la RLS : on cree dans le contexte de l'entreprise.
    with tenant_context(tenant.id):
        return User.objects.create_user(username=username, password=PASSWORD, tenant=tenant, role=role)


@pytest.fixture
def admin_a(tenant_a):
    return make_user(tenant_a, "admin_a")


@pytest.fixture
def admin_b(tenant_b):
    return make_user(tenant_b, "admin_b")


@pytest.fixture
def client_a(admin_a):
    client = APIClient()
    client.force_authenticate(user=admin_a)
    return client


@pytest.fixture
def site_of_tenant_b(tenant_b):
    with tenant_context(tenant_b.id):
        return Site.objects.create(tenant=tenant_b, name="Usine B")


@pytest.fixture
def site_of_tenant_a(tenant_a):
    with tenant_context(tenant_a.id):
        return Site.objects.create(tenant=tenant_a, name="Usine A")
