"""Ecran de reception (decision du proprietaire du 26/11/2026, hors gel du PRD comme US-20).

Un operateur enregistre une livraison sans acces aux referentiels : l'API lui donne les listes utiles
(articles actifs avec unite et conditionnements, fournisseurs actifs) et ses dernieres receptions,
avec ce qu'il peut encore annuler.
"""

from decimal import Decimal

from catalog import services as catalog
from conftest import make_user
from core.tenancy import tenant_context
from lots.tests.conftest import client_for
from tenants.models import User

URL = "/api/v1/lots/receptions/"
OPTIONS = "/api/v1/lots/receptions/options/"


def test_options_give_the_operator_everything_the_form_needs(operator_client, ref_a, tenant_a, admin_a):
    with tenant_context(tenant_a.id):
        catalog.update_article(tenant_id=tenant_a.id, user=admin_a, article=ref_a["biscuit"], is_active=False)
    r = operator_client.get(OPTIONS)
    assert r.status_code == 200, r.json()
    body = r.json()
    articles = {a["code"]: a for a in body["articles"]}
    assert set(articles) == {"MP-FAR", "MP-LAI"}  # article desactive absent
    flour = articles["MP-FAR"]
    assert flour["base_unit"] == "kg" and flour["article_type"] == "matiere" and flour["storage"] == "ambiant"
    assert flour["conversions"] == [{"unit_name": "sac", "factor": "25.000000"}]
    assert articles["MP-LAI"]["storage"] == "refrigere"
    # Fournisseurs seulement (le client « Supermarché » n'y est pas).
    assert [s["name"] for s in body["suppliers"]] == ["Moulins CI"]
    assert {"code": "emballage_abime", "label": "Emballage abîmé"} in body["reception_reasons"]
    assert {"code": "doublon", "label": "Saisie en double"} in body["reversal_reasons"]


def test_reader_has_no_reception_screen(reader_client, ref_a):
    assert reader_client.get(OPTIONS).status_code == 403


def test_options_never_show_another_company(client_b, ref_a):
    body = client_b.get(OPTIONS).json()
    assert body["articles"] == [] and body["suppliers"] == []


def test_recent_receptions_and_what_can_still_be_reversed(operator_client, operator_a, reception_payload, tenant_a,
                                                          admin_a):
    first = operator_client.post(URL, reception_payload, format="json").json()
    second = operator_client.post(URL, dict(reception_payload, supplier_lot_code="F-2"), format="json").json()
    # Le 1er lot a servi : sa reception ne s'annule plus.
    from lots import services

    with tenant_context(tenant_a.id):
        services.record_exit(tenant_id=tenant_a.id, user=admin_a, lot_id=first["id"], movement_type="consommation",
                             quantity=Decimal("1"))
    rows = operator_client.get(URL).json()
    assert [row["lot_code"] for row in rows] == [second["code"], first["code"]]  # plus recente d'abord
    latest = rows[0]
    assert latest["quantity"] == "250.000" and latest["base_unit"] == "kg"
    assert latest["supplier_name"] == "Moulins CI" and latest["username"] == "operateur_a"
    assert latest["can_reverse"] is True
    assert rows[1]["can_reverse"] is False
    r = operator_client.post(f"/api/v1/movements/{latest['movement_id']}/reverse/", {"reason_code": "doublon"},
                             format="json")
    assert r.status_code == 201, r.json()
    latest = operator_client.get(URL).json()[0]
    assert latest["reversed"] is True and latest["can_reverse"] is False
    assert latest["reversal_reason"] == "Saisie en double"


def test_operator_sees_only_own_receptions(operator_client, reception_payload, tenant_a):
    other = client_for(make_user(tenant_a, "operateur_a2", role=User.Role.OPERATEUR))
    other.post(URL, reception_payload, format="json")
    assert operator_client.get(URL).json() == []
    quality = client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE))
    assert len(quality.get(URL).json()) == 1


def test_recent_receptions_of_another_company_are_invisible(operator_client, client_b, reception_payload):
    operator_client.post(URL, reception_payload, format="json")
    assert client_b.get(URL).json() == []
