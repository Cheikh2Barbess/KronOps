"""Filtres combinables des referentiels : articles et fournisseurs ou clients.

Les listes sont paginees : {"count", "next", "previous", "results"}.
Chaque filtre restreint le resultat (ET entre filtres). Dans un meme filtre a plusieurs
valeurs separees par des virgules, c'est OU (ex. type=matiere,fini).
"""

import pytest


def names(response):
    assert response.status_code == 200, response.json()
    return [row["code"] if "code" in row else row["name"] for row in response.json()["results"]]


@pytest.fixture
def catalog_a(client_a, all_absent):
    def article(code, name, article_type, unit="kg", storage="", allergens=None, active=True):
        payload = {"code": code, "name": name, "article_type": article_type, "base_unit": unit, "storage": storage}
        if allergens is not None:
            payload["allergens"] = dict(all_absent, **allergens)
        r = client_a.post("/api/v1/articles/", payload, format="json")
        assert r.status_code == 201, r.json()
        if not active:
            client_a.patch(f"/api/v1/articles/{r.json()['id']}/", {"is_active": False}, format="json")

    article("MP-FAR", "Farine de blé", "matiere", storage="ambiant", allergens={"gluten": "contient"})
    article("MP-LAIT", "Lait en poudre", "matiere", storage="ambiant", allergens={"lait": "contient", "gluten": "peut_contenir"})
    article("MP-SUC", "Sucre", "matiere", storage="ambiant", allergens={})
    article("MP-BEURRE", "Beurre", "matiere", storage="refrigere", allergens={"lait": "contient"}, active=False)
    article("EMB-POT", "Pot verre", "emballage", unit="unite")
    article("PF-BISC", "Biscuit nature", "fini", storage="ambiant")


def test_articles_are_paginated(client_a, catalog_a):
    body = client_a.get("/api/v1/articles/?page_size=2").json()
    assert body["count"] == 6
    assert len(body["results"]) == 2
    assert body["next"] is not None


def test_filter_articles_by_one_or_several_types(client_a, catalog_a):
    assert names(client_a.get("/api/v1/articles/?type=fini")) == ["PF-BISC"]
    assert names(client_a.get("/api/v1/articles/?type=emballage,fini")) == ["EMB-POT", "PF-BISC"]


def test_unknown_type_is_refused(client_a, catalog_a):
    assert client_a.get("/api/v1/articles/?type=bonbon").status_code == 400


def test_search_text_in_code_or_name(client_a, catalog_a):
    assert names(client_a.get("/api/v1/articles/?q=farine")) == ["MP-FAR"]
    assert names(client_a.get("/api/v1/articles/?q=mp-l")) == ["MP-LAIT"]


def test_raw_materials_containing_an_allergen(client_a, catalog_a):
    # Par defaut « present » = contient OU peut contenir.
    assert names(client_a.get("/api/v1/articles/?allergen=gluten")) == ["MP-FAR", "MP-LAIT"]
    assert names(client_a.get("/api/v1/articles/?allergen=gluten&presence=contient")) == ["MP-FAR"]
    assert names(client_a.get("/api/v1/articles/?allergen=gluten&presence=peut_contenir")) == ["MP-LAIT"]
    # Plusieurs allergenes : l'un OU l'autre.
    assert names(client_a.get("/api/v1/articles/?allergen=gluten,lait")) == ["MP-BEURRE", "MP-FAR", "MP-LAIT"]


def test_articles_with_any_allergen_or_none(client_a, catalog_a):
    assert names(client_a.get("/api/v1/articles/?has_allergen=true")) == ["MP-BEURRE", "MP-FAR", "MP-LAIT"]
    # Sans allergene : declare et tout absent. Un article non declare n'est pas « sans allergene ».
    assert names(client_a.get("/api/v1/articles/?has_allergen=false")) == ["MP-SUC"]


def test_free_from_allergen_only_counts_declared_articles(client_a, catalog_a):
    assert names(client_a.get("/api/v1/articles/?allergen_free=gluten")) == ["MP-BEURRE", "MP-SUC"]
    assert names(client_a.get("/api/v1/articles/?allergen_free=gluten,lait")) == ["MP-SUC"]


def test_unknown_allergen_is_refused(client_a, catalog_a):
    assert client_a.get("/api/v1/articles/?allergen=chocolat").status_code == 400


def test_filters_combine(client_a, catalog_a):
    url = "/api/v1/articles/?type=matiere&allergen=lait&active=true&storage=ambiant"
    assert names(client_a.get(url)) == ["MP-LAIT"]
    assert names(client_a.get("/api/v1/articles/?active=false")) == ["MP-BEURRE"]


def test_article_filters_never_show_other_tenant(client_a, catalog_a, article_of_b):
    assert "MP-B" not in names(client_a.get("/api/v1/articles/?q=MP&page_size=200"))
    assert names(client_a.get("/api/v1/articles/?q=Sucre B")) == []


@pytest.fixture
def partners_a(client_a):
    def partner(name, city, supplier=False, customer=False, active=True):
        r = client_a.post(
            "/api/v1/partners/",
            {"name": name, "address": f"Rue 1, {city}", "city": city, "is_supplier": supplier,
             "is_customer": customer, "contact_name": "Mme Traoré"},
            format="json",
        )
        assert r.status_code == 201, r.json()
        if not active:
            client_a.patch(f"/api/v1/partners/{r.json()['id']}/", {"is_active": False}, format="json")

    partner("Moulins Abidjan", "Abidjan", supplier=True)
    partner("Supermarché Plateau", "abidjan ", customer=True)
    partner("Coopérative Soubré", "Soubré", supplier=True, customer=True)
    partner("Grossiste Bouaké", "Bouaké", customer=True, active=False)


def test_city_is_stored_trimmed(client_a, partners_a):
    rows = client_a.get("/api/v1/partners/?q=Plateau").json()["results"]
    assert rows[0]["city"] == "abidjan"


def test_filter_partners_by_role(client_a, partners_a):
    assert names(client_a.get("/api/v1/partners/?role=supplier")) == ["Coopérative Soubré", "Moulins Abidjan"]
    assert names(client_a.get("/api/v1/partners/?role=customer")) == [
        "Coopérative Soubré", "Grossiste Bouaké", "Supermarché Plateau"]
    assert names(client_a.get("/api/v1/partners/?role=both")) == ["Coopérative Soubré"]


def test_filter_partners_by_city_ignores_case(client_a, partners_a):
    assert names(client_a.get("/api/v1/partners/?city=ABIDJAN")) == ["Moulins Abidjan", "Supermarché Plateau"]
    assert names(client_a.get("/api/v1/partners/?city=Abidjan,Soubré")) == [
        "Coopérative Soubré", "Moulins Abidjan", "Supermarché Plateau"]


def test_partner_filters_combine(client_a, partners_a):
    assert names(client_a.get("/api/v1/partners/?role=customer&city=abidjan")) == ["Supermarché Plateau"]
    assert names(client_a.get("/api/v1/partners/?role=customer&active=true")) == [
        "Coopérative Soubré", "Supermarché Plateau"]
    assert names(client_a.get("/api/v1/partners/?q=Traoré&city=Bouaké")) == ["Grossiste Bouaké"]


def test_city_list_groups_spellings(client_a, partners_a):
    cities = client_a.get("/api/v1/partners/cities/").json()
    assert [(c["city"].lower(), c["count"]) for c in cities] == [("abidjan", 2), ("bouaké", 1), ("soubré", 1)]


def test_city_list_is_isolated_per_tenant(client_a, client_b, partners_a):
    client_b.post(
        "/api/v1/partners/",
        {"name": "Client B", "address": "Yamoussoukro", "city": "Yamoussoukro", "is_customer": True},
        format="json",
    )
    assert "Yamoussoukro" not in [c["city"] for c in client_a.get("/api/v1/partners/cities/").json()]
    assert names(client_a.get("/api/v1/partners/?city=Yamoussoukro")) == []


def test_operator_cannot_read_city_list(operator_client):
    assert operator_client.get("/api/v1/partners/cities/").status_code == 403


def test_search_ignores_accents_and_case(client_a, catalog_a, partners_a):
    assert names(client_a.get("/api/v1/articles/?q=farine de ble")) == ["MP-FAR"]
    assert names(client_a.get("/api/v1/articles/?q=BLÉ")) == ["MP-FAR"]
    assert names(client_a.get("/api/v1/partners/?q=cooperative soubre")) == ["Coopérative Soubré"]
    assert names(client_a.get("/api/v1/partners/?q=traore&city=Bouaké")) == ["Grossiste Bouaké"]
