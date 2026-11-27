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
def client_b(admin_b):
    client = APIClient()
    client.force_authenticate(user=admin_b)
    return client


@pytest.fixture
def site_of_tenant_b(tenant_b):
    with tenant_context(tenant_b.id):
        return Site.objects.create(tenant=tenant_b, name="Usine B")


@pytest.fixture
def site_of_tenant_a(tenant_a):
    with tenant_context(tenant_a.id):
        return Site.objects.create(tenant=tenant_a, name="Usine A")


@pytest.fixture
def orchard(tenant_a, admin_a):
    """Referentiel « fruits seches bio » du client A : producteurs, parcelles (bio, conversion, conventionnelle),
    mangue fraiche, mangue sechee en vrac (rendement attendu 5,5 a 7,7 %), carton de 10 kg, palette, sechoirs."""
    from decimal import Decimal

    from catalog import services as catalog
    from catalog.selectors import allergen_codes
    from production import services as production

    absent = {c: "absent" for c in allergen_codes()}
    t, u = tenant_a.id, admin_a
    with tenant_context(t):
        r = {}
        r["fresh"] = catalog.create_article(
            tenant_id=t, user=u, code="MGF", name="Mangue fraîche", article_type="matiere", base_unit="kg",
            storage="ambiant", allergens=absent,
        )
        catalog.create_conversion(tenant_id=t, user=u, article=r["fresh"], unit_name="caisse", factor=Decimal("20"))
        r["dried"] = catalog.create_article(
            tenant_id=t, user=u, code="MGS", name="Mangue séchée vrac", article_type="semi_fini", base_unit="kg",
            storage="ambiant", shelf_life_days=365, yield_min_pct=Decimal("5.5"), yield_max_pct=Decimal("7.7"),
        )
        r["carton"] = catalog.create_article(
            tenant_id=t, user=u, code="MGC", name="Mangue séchée, carton vrac", article_type="fini", base_unit="kg",
            storage="ambiant", shelf_life_days=365,
        )
        catalog.create_conversion(tenant_id=t, user=u, article=r["carton"], unit_name="carton", factor=Decimal("10"))
        r["box"] = catalog.create_article(
            tenant_id=t, user=u, code="CTV", name="Carton vide", article_type="emballage", base_unit="unite",
        )
        r["producer"] = catalog.create_partner(
            tenant_id=t, user=u, name="Producteur Un", is_supplier=True, address="Village Un",
        )
        r["producer2"] = catalog.create_partner(
            tenant_id=t, user=u, name="Producteur Deux", is_supplier=True, address="Village Deux",
        )
        r["customer"] = catalog.create_partner(
            tenant_id=t, user=u, name="Importateur", is_customer=True, address="Port", city="Rotterdam",
        )
        r["p_bio"] = catalog.create_parcel(tenant_id=t, user=u, producer=r["producer"], code="P-BIO",
                                           organic_status="bio")
        r["p_conv"] = catalog.create_parcel(tenant_id=t, user=u, producer=r["producer2"], code="P-CONV",
                                            organic_status="conventionnel")
        r["p_bio2"] = catalog.create_parcel(tenant_id=t, user=u, producer=r["producer2"], code="P-BIO2",
                                            organic_status="bio")
        r["dryer1"] = production.create_equipment(tenant_id=t, user=u, code="SEC-1", name="Séchoir 1",
                                                  equipment_type="sechoir")
        r["dryer2"] = production.create_equipment(tenant_id=t, user=u, code="SEC-2", name="Séchoir 2",
                                                  equipment_type="sechoir")
    return r


@pytest.fixture
def receive_fresh(tenant_a, admin_a, orchard):
    """Reception de mangue fraiche depuis une parcelle (statut bio recopie)."""
    import datetime
    from decimal import Decimal

    from lots import services as lots

    def receive(parcel, kg):
        with tenant_context(tenant_a.id):
            return lots.receive_lot(
                tenant_id=tenant_a.id, user=admin_a, article=orchard["fresh"], supplier=parcel.producer,
                supplier_lot_code="", quantity=Decimal(kg), unit="kg", date_type="ddm",
                expiry_date=datetime.date.today() + datetime.timedelta(days=10), parcel=parcel,
            )

    return receive
