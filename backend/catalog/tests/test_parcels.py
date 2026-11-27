"""Parcelles des producteurs et rendement attendu des articles (suivi bio, bilan matiere)."""

from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from audit.models import AuditLog
from catalog import services
from core.tenancy import tenant_context

URL = "/api/v1/parcels/"


def test_admin_creates_a_parcel_for_a_supplier(client_a, orchard, tenant_a):
    response = client_a.post(URL, {"producer": str(orchard["producer"].id), "code": "P-NEW", "locality": "Village",
                                   "area_ha": "2.5", "organic_status": "conversion"}, format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["producer_name"] == "Producteur Un"
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="catalog.parcel", action="create").count() == 4


def test_parcel_code_is_unique_and_producer_must_be_a_supplier(client_a, orchard):
    dup = client_a.post(URL, {"producer": str(orchard["producer"].id), "code": "p-bio", "organic_status": "bio"},
                        format="json")
    assert dup.status_code == 400
    customer = client_a.post(URL, {"producer": str(orchard["customer"].id), "code": "P-X", "organic_status": "bio"},
                             format="json")
    assert customer.status_code == 400


def test_status_change_is_audited(client_a, orchard):
    url = f"{URL}{orchard['p_conv'].id}/"
    response = client_a.patch(url, {"organic_status": "conversion"}, format="json")
    assert response.status_code == 200
    assert response.json()["organic_status"] == "conversion"


def test_isolation_parcel_of_other_company_is_404(client_b, orchard):
    assert client_b.get(f"{URL}{orchard['p_bio'].id}/").status_code == 404
    assert client_b.get(URL).json()["count"] == 0


def test_isolation_cannot_attach_parcel_to_other_company_producer(client_b, orchard):
    response = client_b.post(URL, {"producer": str(orchard["producer"].id), "code": "P-Y", "organic_status": "bio"},
                             format="json")
    assert response.status_code == 400


@pytest.mark.parametrize("minimum,maximum", [("8", "5"), ("0", "5"), ("5", "120"), ("5", None)])
def test_yield_range_must_be_coherent(tenant_a, admin_a, minimum, maximum):
    with tenant_context(tenant_a.id), pytest.raises(ValidationError):
        services.create_article(
            tenant_id=tenant_a.id, user=admin_a, code="X", name="X", article_type="semi_fini", base_unit="kg",
            yield_min_pct=Decimal(minimum), yield_max_pct=Decimal(maximum) if maximum else None,
        )
