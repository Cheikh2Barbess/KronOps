"""US-02 Referentiels : articles et allergenes."""

from audit.models import AuditLog
from catalog.models import Article, ArticleAllergen
from core.tenancy import tenant_context
from events.models import OutboxEvent


def test_reference_list_has_the_14_eu_allergens(allergen_codes):
    assert len(allergen_codes) == 14
    assert {"gluten", "lait", "sesame", "sulfites", "mollusques"} <= set(allergen_codes)


def test_quality_creates_raw_material_with_full_allergen_declaration(quality_client, flour_payload, tenant_a):
    response = quality_client.post("/api/v1/articles/", flour_payload, format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["allergens"]["gluten"] == "contient"
    assert body["allergens"]["lait"] == "absent"
    assert body["allergens_declared"] is True
    with tenant_context(tenant_a.id):
        article = Article.objects.get(pk=body["id"])
        assert ArticleAllergen.objects.filter(article=article).count() == 14
        assert AuditLog.objects.filter(entity_id=article.id, action="create").exists()
        assert OutboxEvent.objects.filter(event_type="article.created").count() == 1


def test_raw_material_without_allergen_declaration_is_refused(client_a, flour_payload):
    del flour_payload["allergens"]
    response = client_a.post("/api/v1/articles/", flour_payload, format="json")
    assert response.status_code == 400
    assert "allergens" in response.json()


def test_partial_allergen_declaration_is_refused(client_a, flour_payload):
    flour_payload["allergens"] = {"gluten": "contient"}
    response = client_a.post("/api/v1/articles/", flour_payload, format="json")
    assert response.status_code == 400
    assert "allergens" in response.json()


def test_unknown_allergen_or_presence_is_refused(client_a, flour_payload):
    flour_payload["allergens"]["gluten"] = "un_peu"
    assert client_a.post("/api/v1/articles/", flour_payload, format="json").status_code == 400
    flour_payload["allergens"]["gluten"] = "contient"
    flour_payload["allergens"]["chocolat"] = "contient"
    assert client_a.post("/api/v1/articles/", flour_payload, format="json").status_code == 400


def test_packaging_needs_no_allergen_declaration(client_a):
    response = client_a.post(
        "/api/v1/articles/",
        {"code": "EMB-01", "name": "Sachet 1 kg", "article_type": "emballage", "base_unit": "unite"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["allergens_declared"] is False


def test_code_is_unique_per_tenant_but_not_across_tenants(client_a, flour_payload, article_of_b):
    assert client_a.post("/api/v1/articles/", flour_payload, format="json").status_code == 201
    assert client_a.post("/api/v1/articles/", flour_payload, format="json").status_code == 400
    flour_payload["code"] = article_of_b["code"]
    assert client_a.post("/api/v1/articles/", flour_payload, format="json").status_code == 201


def test_shelf_life_must_be_positive(client_a, flour_payload):
    flour_payload["shelf_life_days"] = 0
    assert client_a.post("/api/v1/articles/", flour_payload, format="json").status_code == 400


def test_update_article_is_audited_with_old_and_new_values(client_a, flour_payload, tenant_a):
    article_id = client_a.post("/api/v1/articles/", flour_payload, format="json").json()["id"]
    allergens = dict(flour_payload["allergens"], lait="peut_contenir")
    response = client_a.patch(
        f"/api/v1/articles/{article_id}/", {"name": "Farine T65", "allergens": allergens}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert response.json()["allergens"]["lait"] == "peut_contenir"
    with tenant_context(tenant_a.id):
        entry = AuditLog.objects.get(entity_id=article_id, action="update")
        assert entry.old_values["name"] == "Farine de blé T55"
        assert entry.new_values["name"] == "Farine T65"
        assert entry.old_values["allergens"]["lait"] == "absent"
        assert entry.new_values["allergens"]["lait"] == "peut_contenir"


def test_base_unit_cannot_change(client_a, flour_payload):
    article_id = client_a.post("/api/v1/articles/", flour_payload, format="json").json()["id"]
    response = client_a.patch(f"/api/v1/articles/{article_id}/", {"base_unit": "l"}, format="json")
    assert response.status_code == 400


def test_article_cannot_be_deleted_only_deactivated(client_a, flour_payload):
    article_id = client_a.post("/api/v1/articles/", flour_payload, format="json").json()["id"]
    assert client_a.delete(f"/api/v1/articles/{article_id}/").status_code == 405
    response = client_a.patch(f"/api/v1/articles/{article_id}/", {"is_active": False}, format="json")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_list_filters_by_type(client_a, flour_payload):
    client_a.post("/api/v1/articles/", flour_payload, format="json")
    client_a.post(
        "/api/v1/articles/",
        {"code": "EMB-01", "name": "Sachet", "article_type": "emballage", "base_unit": "unite"},
        format="json",
    )
    response = client_a.get("/api/v1/articles/?type=emballage")
    assert [a["code"] for a in response.json()] == ["EMB-01"]


def test_allergen_list_endpoint(production_client):
    response = production_client.get("/api/v1/allergens/")
    assert response.status_code == 200
    assert len(response.json()) == 14


# Droits (matrice du PRD) -------------------------------------------------


def test_production_can_read_but_not_write(production_client, flour_payload):
    assert production_client.get("/api/v1/articles/").status_code == 200
    assert production_client.post("/api/v1/articles/", flour_payload, format="json").status_code == 403


def test_operator_cannot_read_referentials(operator_client):
    assert operator_client.get("/api/v1/articles/").status_code == 403


# Isolation entre clients --------------------------------------------------


def test_article_of_other_tenant_is_404(client_a, article_of_b):
    url = f"/api/v1/articles/{article_of_b['id']}/"
    assert client_a.get(url).status_code == 404
    assert client_a.patch(url, {"name": "Pirate"}, format="json").status_code == 404


def test_article_list_only_shows_own_tenant(client_a, flour_payload, article_of_b):
    client_a.post("/api/v1/articles/", flour_payload, format="json")
    codes = [a["code"] for a in client_a.get("/api/v1/articles/").json()]
    assert codes == ["MP-FAR-01"]


def test_tenant_in_body_is_ignored(client_a, flour_payload, tenant_a, tenant_b):
    flour_payload["tenant"] = str(tenant_b.id)
    article_id = client_a.post("/api/v1/articles/", flour_payload, format="json").json()["id"]
    with tenant_context(tenant_a.id):
        assert Article.objects.get(pk=article_id).tenant_id == tenant_a.id
