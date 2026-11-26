"""US-02 / regle Unites : conversions explicites par article."""

from decimal import Decimal


def make_article(client, code="MP-SUC", unit="kg", all_absent=None):
    payload = {"code": code, "name": "Sucre", "article_type": "matiere", "base_unit": unit, "allergens": all_absent}
    response = client.post("/api/v1/articles/", payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def test_create_conversion(client_a, all_absent):
    article_id = make_article(client_a, all_absent=all_absent)
    url = f"/api/v1/articles/{article_id}/conversions/"
    response = client_a.post(url, {"unit_name": "sac", "factor": "25"}, format="json")
    assert response.status_code == 201, response.json()
    assert Decimal(response.json()["factor"]) == Decimal("25")
    assert [c["unit_name"] for c in client_a.get(url).json()] == ["sac"]


def test_factor_must_be_positive(client_a, all_absent):
    article_id = make_article(client_a, all_absent=all_absent)
    url = f"/api/v1/articles/{article_id}/conversions/"
    assert client_a.post(url, {"unit_name": "sac", "factor": "0"}, format="json").status_code == 400
    assert client_a.post(url, {"unit_name": "sac", "factor": "-1"}, format="json").status_code == 400


def test_conversion_to_another_base_unit_is_refused(client_a, all_absent):
    # Pas de conversion kg <-> L (densite non geree).
    article_id = make_article(client_a, all_absent=all_absent)
    url = f"/api/v1/articles/{article_id}/conversions/"
    assert client_a.post(url, {"unit_name": "l", "factor": "1"}, format="json").status_code == 400
    assert client_a.post(url, {"unit_name": "kg", "factor": "1"}, format="json").status_code == 400


def test_duplicate_unit_name_is_refused(client_a, all_absent):
    article_id = make_article(client_a, all_absent=all_absent)
    url = f"/api/v1/articles/{article_id}/conversions/"
    assert client_a.post(url, {"unit_name": "sac", "factor": "25"}, format="json").status_code == 201
    assert client_a.post(url, {"unit_name": "Sac", "factor": "50"}, format="json").status_code == 400


def test_conversion_on_other_tenant_article_is_404(client_a, article_of_b):
    url = f"/api/v1/articles/{article_of_b['id']}/conversions/"
    assert client_a.get(url).status_code == 404
    assert client_a.post(url, {"unit_name": "sac", "factor": "25"}, format="json").status_code == 404


def test_production_cannot_create_conversion(client_a, production_client, all_absent):
    article_id = make_article(client_a, all_absent=all_absent)
    url = f"/api/v1/articles/{article_id}/conversions/"
    assert production_client.post(url, {"unit_name": "sac", "factor": "25"}, format="json").status_code == 403
