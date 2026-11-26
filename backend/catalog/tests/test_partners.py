"""US-02 Referentiels : fournisseurs et clients."""

from audit.models import AuditLog
from core.tenancy import tenant_context

SUPPLIER = {
    "name": "Moulins de Côte d'Ivoire",
    "is_supplier": True,
    "address": "Zone portuaire, Abidjan",
    "contact_name": "M. Koné",
    "phone": "+225 01 02 03 04 05",
}


def test_create_supplier_is_audited(client_a, tenant_a):
    response = client_a.post("/api/v1/partners/", SUPPLIER, format="json")
    assert response.status_code == 201, response.json()
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_id=response.json()["id"], action="create").exists()


def test_partner_must_be_supplier_or_customer(client_a):
    payload = dict(SUPPLIER, is_supplier=False, is_customer=False)
    assert client_a.post("/api/v1/partners/", payload, format="json").status_code == 400


def test_address_is_required(client_a):
    # Le nom et l'adresse du fournisseur et du client sont exiges pour la tracabilite.
    payload = dict(SUPPLIER, address="")
    assert client_a.post("/api/v1/partners/", payload, format="json").status_code == 400


def test_filter_suppliers_and_customers(client_a):
    client_a.post("/api/v1/partners/", SUPPLIER, format="json")
    client_a.post(
        "/api/v1/partners/",
        {"name": "Supermarché Plateau", "is_customer": True, "address": "Plateau, Abidjan"},
        format="json",
    )
    assert [p["name"] for p in client_a.get("/api/v1/partners/?role=customer").json()] == ["Supermarché Plateau"]
    assert [p["name"] for p in client_a.get("/api/v1/partners/?role=supplier").json()] == [SUPPLIER["name"]]


def test_update_partner(client_a):
    partner_id = client_a.post("/api/v1/partners/", SUPPLIER, format="json").json()["id"]
    response = client_a.patch(f"/api/v1/partners/{partner_id}/", {"is_customer": True}, format="json")
    assert response.status_code == 200
    assert response.json()["is_customer"] is True
    assert client_a.delete(f"/api/v1/partners/{partner_id}/").status_code == 405


def test_partner_of_other_tenant_is_404(client_a, client_b):
    partner_id = client_b.post("/api/v1/partners/", SUPPLIER, format="json").json()["id"]
    assert client_a.get(f"/api/v1/partners/{partner_id}/").status_code == 404
    assert client_a.patch(f"/api/v1/partners/{partner_id}/", {"name": "X"}, format="json").status_code == 404
    assert client_a.get("/api/v1/partners/").json() == []


def test_operator_cannot_read_partners(operator_client):
    assert operator_client.get("/api/v1/partners/").status_code == 403
