import pytest
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.selectors import allergen_codes
from conftest import make_user
from core.tenancy import tenant_context
from tenants.models import User


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def operator_a(tenant_a):
    return make_user(tenant_a, "operateur_a", role=User.Role.OPERATEUR)


@pytest.fixture
def operator_client(operator_a):
    return client_for(operator_a)


@pytest.fixture
def reader_client(tenant_a):
    return client_for(make_user(tenant_a, "lecture_a", role=User.Role.LECTURE))


def _absent():
    return {c: "absent" for c in allergen_codes()}


@pytest.fixture
def ref_a(tenant_a, admin_a):
    """Referentiel minimal du client A : farine (kg, conversion sac = 25 kg), lait refrigere, biscuit fini,
    un fournisseur et un client."""
    with tenant_context(tenant_a.id):
        flour = catalog.create_article(
            tenant_id=tenant_a.id, user=admin_a, code="MP-FAR", name="Farine", article_type="matiere",
            base_unit="kg", storage="ambiant", allergens=dict(_absent(), gluten="contient"),
        )
        catalog.create_conversion(tenant_id=tenant_a.id, user=admin_a, article=flour, unit_name="sac", factor=25)
        milk = catalog.create_article(
            tenant_id=tenant_a.id, user=admin_a, code="MP-LAI", name="Lait", article_type="matiere",
            base_unit="l", storage="refrigere", allergens=dict(_absent(), lait="contient"),
        )
        biscuit = catalog.create_article(
            tenant_id=tenant_a.id, user=admin_a, code="PF-BIS", name="Biscuit", article_type="fini",
            base_unit="unite", shelf_life_days=120,
        )
        supplier = catalog.create_partner(
            tenant_id=tenant_a.id, user=admin_a, name="Moulins CI", is_supplier=True, address="Abidjan"
        )
        customer = catalog.create_partner(
            tenant_id=tenant_a.id, user=admin_a, name="Supermarché", is_customer=True, address="Plateau"
        )
    return {"flour": flour, "milk": milk, "biscuit": biscuit, "supplier": supplier, "customer": customer}


@pytest.fixture
def reception_payload(ref_a):
    return {
        "article": str(ref_a["flour"].id),
        "supplier": str(ref_a["supplier"].id),
        "supplier_lot_code": "F-2026-118",
        "quantity": "10",
        "unit": "sac",
        "date_type": "ddm",
        "expiry_date": "2027-06-30",
        "visual_ok": True,
        "organic_status": "conventionnel",
    }
