"""US-03 Journal d'audit : le RQ voit qui a cree, modifie ou annule, quand, avec ancienne et nouvelle valeur."""

import pytest
from rest_framework.test import APIClient

from conftest import make_user
from tenants.models import User


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def quality_a(tenant_a):
    return client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE))


@pytest.fixture
def partner_history(client_a):
    """Un partenaire cree puis modifie par admin_a : deux lignes d'audit."""
    payload = {"name": "Moulins CI", "is_supplier": True, "address": "Abidjan"}
    partner_id = client_a.post("/api/v1/partners/", payload, format="json").json()["id"]
    client_a.patch(f"/api/v1/partners/{partner_id}/", {"address": "San-Pédro"}, format="json")
    return partner_id


def test_quality_sees_who_did_what_and_when(quality_a, partner_history):
    response = quality_a.get("/api/v1/audit/")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    latest, first = body["results"]  # plus recent d'abord
    assert latest["action"] == "update"
    assert latest["username"] == "admin_a"
    assert latest["entity_type"] == "catalog.partner"
    assert latest["entity_label"] == "partenaire"
    assert latest["entity_id"] == partner_history
    assert latest["old_values"]["address"] == "Abidjan"
    assert latest["new_values"]["address"] == "San-Pédro"
    assert latest["changed_fields"] == ["address"]
    assert latest["created_at"]
    assert first["action"] == "create"


def test_filter_by_entity(quality_a, client_a, partner_history):
    client_a.post("/api/v1/partners/", {"name": "Autre", "is_customer": True, "address": "Bouaké"}, format="json")
    response = quality_a.get(f"/api/v1/audit/?entity_id={partner_history}")
    assert [e["entity_id"] for e in response.json()["results"]] == [partner_history, partner_history]


def test_filter_by_action_type_and_user(quality_a, client_a, partner_history, admin_a):
    assert quality_a.get("/api/v1/audit/?action=update").json()["count"] == 1
    assert quality_a.get("/api/v1/audit/?entity_type=catalog.partner").json()["count"] == 2
    assert quality_a.get("/api/v1/audit/?entity_type=catalog.article").json()["count"] == 0
    assert quality_a.get(f"/api/v1/audit/?user={admin_a.id}").json()["count"] == 2


def test_filter_by_date(quality_a, partner_history):
    assert quality_a.get("/api/v1/audit/?date_from=2000-01-01").json()["count"] == 2
    assert quality_a.get("/api/v1/audit/?date_to=2000-01-01").json()["count"] == 0
    assert quality_a.get("/api/v1/audit/?date_from=pas-une-date").status_code == 400


def test_pagination(quality_a, client_a):
    for i in range(5):
        client_a.post("/api/v1/partners/", {"name": f"P{i}", "is_customer": True, "address": "A"}, format="json")
    first = quality_a.get("/api/v1/audit/?page_size=2").json()
    assert first["count"] == 5 and len(first["results"]) == 2 and first["next"]
    last = quality_a.get("/api/v1/audit/?page_size=2&page=3").json()
    assert len(last["results"]) == 1 and last["next"] is None


def test_list_of_users_for_the_filter(quality_a, admin_a, admin_b):
    usernames = [u["username"] for u in quality_a.get("/api/v1/audit/users/").json()]
    assert "admin_a" in usernames and "admin_b" not in usernames


# Droits : Admin et Qualite en lecture, les autres non (matrice du PRD) ----


@pytest.mark.parametrize("role", [User.Role.PRODUCTION, User.Role.OPERATEUR, User.Role.LECTURE])
def test_other_roles_cannot_read_audit(tenant_a, role):
    client = client_for(make_user(tenant_a, f"u_{role}", role=role))
    assert client.get("/api/v1/audit/").status_code == 403
    assert client.get("/api/v1/audit/users/").status_code == 403


def test_admin_can_read_audit(client_a, partner_history):
    assert client_a.get("/api/v1/audit/").status_code == 200


def test_audit_is_read_only_through_api(client_a, partner_history):
    assert client_a.post("/api/v1/audit/", {"action": "faux"}, format="json").status_code == 405
    assert client_a.delete("/api/v1/audit/").status_code == 405


# Isolation entre clients ---------------------------------------------------


def test_audit_of_other_tenant_is_invisible(quality_a, admin_b):
    client_b = client_for(admin_b)
    partner_b = client_b.post(
        "/api/v1/partners/", {"name": "Secret B", "is_supplier": True, "address": "X"}, format="json"
    ).json()["id"]
    assert quality_a.get("/api/v1/audit/").json()["count"] == 0
    assert quality_a.get(f"/api/v1/audit/?entity_id={partner_b}").json()["count"] == 0
