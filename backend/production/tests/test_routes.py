"""Parcours d'etapes par produit : la mangue et la coco n'ont pas les memes etapes.

Un parcours regroupe des articles (frais, semi-fini, fini d'un meme produit) et la liste des etapes permises.
Une etape hors parcours est refusee pour ces articles. Un article sans parcours (ou dans un parcours desactive)
suit les etapes actives de l'entreprise.
"""

from rest_framework.test import APIClient

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from production.models import ProductRoute
from tenants.models import User

ROUTES = "/api/v1/production/routes/"
STEPS = "/api/v1/production/steps/"
OPTIONS = "/api/v1/production/runs/options/"
RUNS = "/api/v1/production/runs/"

MANGO_STEPS = ["murissement", "tri", "sechage", "conditionnement"]


def mango_route(client, orchard, steps=None, articles=None, name="Mangue séchée"):
    keys = articles or ["fresh", "dried", "carton"]
    return client.post(ROUTES, {
        "name": name, "steps": steps or MANGO_STEPS, "articles": [str(orchard[k].id) for k in keys],
    }, format="json")


def declare(client, orchard, lot, step, article="dried", kg="100", out="7"):
    return client.post(RUNS, {
        "step": step, "output_article": str(orchard[article].id), "output_quantity": out,
        "inputs": [{"lot": str(lot.id), "quantity": kg}],
    }, format="json")


def test_admin_creates_a_route_with_steps_and_articles(client_a, orchard, tenant_a):
    response = mango_route(client_a, orchard)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["name"] == "Mangue séchée"
    assert body["is_active"] is True
    # Les etapes gardent l'ordre choisi pour ce parcours.
    assert [s["code"] for s in body["steps"]] == MANGO_STEPS
    assert all(s["label"] for s in body["steps"])
    assert sorted(a["code"] for a in body["articles"]) == ["MGC", "MGF", "MGS"]
    assert [r["id"] for r in client_a.get(ROUTES).json()] == [body["id"]]
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="production.productroute", action="create").exists()
        assert OutboxEvent.objects.filter(event_type="production.route_created").count() == 1


def test_step_outside_the_route_is_refused_for_its_articles(client_a, orchard, receive_fresh):
    mango_route(client_a, orchard)
    fresh = receive_fresh(orchard["p_bio"], "300")
    # « preparation » est active pour l'entreprise mais absente du parcours de la mangue.
    refused = declare(client_a, orchard, fresh, "preparation", out="90")
    assert refused.status_code == 400
    assert "parcours" in refused.json()["step"][0]
    assert declare(client_a, orchard, fresh, "sechage").status_code == 201


def test_consumed_lot_must_follow_its_route_too(client_a, orchard, receive_fresh):
    # Parcours limite a la mangue fraiche : elle ne peut que murir.
    mango_route(client_a, orchard, steps=["murissement"], articles=["fresh"], name="Mangue fraîche")
    fresh = receive_fresh(orchard["p_bio"], "300")
    refused = declare(client_a, orchard, fresh, "sechage")
    assert refused.status_code == 400
    assert "parcours" in refused.json()["inputs"][0]
    assert declare(client_a, orchard, fresh, "murissement", article="fresh", out="95").status_code == 201


def test_article_without_route_follows_company_steps(client_a, orchard, receive_fresh):
    mango_route(client_a, orchard, articles=["carton"])
    fresh = receive_fresh(orchard["p_bio"], "300")
    assert declare(client_a, orchard, fresh, "preparation", out="90").status_code == 201


def test_deactivated_route_no_longer_restricts(client_a, orchard, receive_fresh):
    route = mango_route(client_a, orchard).json()
    fresh = receive_fresh(orchard["p_bio"], "300")
    assert declare(client_a, orchard, fresh, "preparation", out="90").status_code == 400
    response = client_a.put(f"{ROUTES}{route['id']}/", {
        "name": route["name"], "is_active": False, "steps": MANGO_STEPS,
        "articles": [a["id"] for a in route["articles"]],
    }, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["is_active"] is False
    assert declare(client_a, orchard, fresh, "preparation", out="90").status_code == 201


def test_update_replaces_steps_and_articles(client_a, orchard, tenant_a):
    route = mango_route(client_a, orchard).json()
    response = client_a.put(f"{ROUTES}{route['id']}/", {
        "name": "Mangue bio", "is_active": True, "steps": ["sechage", "tri"],
        "articles": [str(orchard["dried"].id)],
    }, format="json")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["name"] == "Mangue bio"
    # L'ordre envoye est l'ordre du parcours, meme s'il differe de celui de l'entreprise.
    assert [s["code"] for s in body["steps"]] == ["sechage", "tri"]
    assert [a["code"] for a in body["articles"]] == ["MGS"]
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="production.productroute", action="update").exists()
        assert OutboxEvent.objects.filter(event_type="production.route_updated").count() == 1


def test_options_give_each_article_and_lot_its_route_steps(client_a, orchard, receive_fresh):
    mango_route(client_a, orchard, articles=["fresh", "dried"])
    receive_fresh(orchard["p_bio"], "300")
    body = client_a.get(OPTIONS).json()
    by_code = {a["code"]: a for a in body["output_articles"]}
    assert by_code["MGS"]["route_steps"] == MANGO_STEPS
    assert by_code["MGC"]["route_steps"] is None
    assert body["lots"][0]["route_steps"] == MANGO_STEPS


def test_route_steps_must_be_active_for_the_company(client_a, orchard):
    response = mango_route(client_a, orchard, steps=["lavage", "sechage"])
    assert response.status_code == 400
    assert "steps" in response.json()
    client_a.put(STEPS, {"steps": [{"code": c, "is_active": True} for c in ["lavage", "sechage"]]}, format="json")
    assert mango_route(client_a, orchard, steps=["lavage", "sechage"]).status_code == 201


def test_invalid_routes_are_refused(client_a, orchard):
    cases = [
        ({"steps": []}, "steps"),
        ({"steps": ["inconnue"]}, "steps"),
        ({"steps": ["sechage", "sechage"]}, "steps"),
        ({"name": "  "}, "name"),
        ({"articles": []}, "articles"),
        ({"articles": [str(orchard["box"].id)]}, "articles"),
        ({"articles": ["00000000-0000-0000-0000-000000000000"]}, "articles"),
    ]
    for patch, field in cases:
        payload = {"name": "Mangue", "steps": MANGO_STEPS, "articles": [str(orchard["dried"].id)], **patch}
        response = client_a.post(ROUTES, payload, format="json")
        assert response.status_code == 400, (patch, response.json())
        assert field in response.json(), (patch, response.json())


def test_an_article_belongs_to_one_route_and_names_are_unique(client_a, orchard):
    assert mango_route(client_a, orchard, articles=["fresh", "dried"]).status_code == 201
    twice = mango_route(client_a, orchard, articles=["dried"], name="Autre")
    assert twice.status_code == 400
    assert "Mangue séchée" in twice.json()["articles"][0]
    same_name = mango_route(client_a, orchard, articles=["carton"], name="mangue SÉCHÉE")
    assert same_name.status_code == 400
    assert "name" in same_name.json()


def test_only_admin_writes_routes(tenant_a, orchard):
    for role in [User.Role.QUALITE, User.Role.PRODUCTION, User.Role.OPERATEUR, User.Role.LECTURE]:
        client = APIClient()
        client.force_authenticate(make_user(tenant_a, f"r_{role}", role=role))
        assert mango_route(client, orchard).status_code == 403
        assert client.get(ROUTES).status_code == (403 if role == User.Role.OPERATEUR else 200)


def test_isolation_between_companies(client_a, client_b, orchard, tenant_b):
    route = mango_route(client_a, orchard).json()
    assert client_b.get(ROUTES).json() == []
    assert client_b.get(f"{ROUTES}{route['id']}/").status_code == 404
    put = client_b.put(f"{ROUTES}{route['id']}/", {"name": "X", "is_active": True, "steps": ["sechage"],
                                                  "articles": []}, format="json")
    assert put.status_code == 404
    # Les articles du client A sont introuvables pour le client B.
    stolen = client_b.post(ROUTES, {"name": "X", "steps": ["sechage"], "articles": [str(orchard["dried"].id)]},
                           format="json")
    assert stolen.status_code == 400
    with tenant_context(tenant_b.id):
        assert ProductRoute.objects.count() == 0


COCO = ["cassage", "parage", "lavage", "rapage", "sechage", "conditionnement"]


def test_each_route_has_its_own_order(client_a, orchard):
    """Coco : cassage et parage avant le lavage, alors que l'entreprise range le lavage en premier."""
    client_a.put(STEPS, {"steps": [{"code": c, "is_active": True} for c in
                                   ["murissement", "lavage", "tri", "cassage", "parage", "rapage", "sechage",
                                    "conditionnement"]]}, format="json")
    coco = mango_route(client_a, orchard, steps=COCO, articles=["carton"], name="Coco râpée").json()
    assert [s["code"] for s in coco["steps"]] == COCO
    mango = mango_route(client_a, orchard, steps=["murissement", "lavage", "tri", "sechage"],
                        articles=["fresh", "dried"]).json()
    assert [s["code"] for s in mango["steps"]] == ["murissement", "lavage", "tri", "sechage"]
    options = client_a.get(OPTIONS).json()
    assert {a["code"]: a["route_steps"] for a in options["output_articles"]}["MGC"] == COCO
    assert {a["code"]: a["route_id"] for a in options["output_articles"]}["MGC"] == coco["id"]
    # L'ecran de declaration propose chaque parcours avec ses etapes dans son ordre.
    assert {r["name"]: r["steps"] for r in options["routes"]}["Coco râpée"] == COCO

    # Reordonner le parcours sans changer ses etapes.
    reordered = ["lavage", "cassage", "parage", "rapage", "sechage", "conditionnement"]
    response = client_a.put(f"{ROUTES}{coco['id']}/", {"name": "Coco râpée", "is_active": True, "steps": reordered,
                                                       "articles": [str(orchard["carton"].id)]}, format="json")
    assert response.status_code == 200, response.json()
    assert [s["code"] for s in response.json()["steps"]] == reordered
    assert [s["code"] for s in client_a.get(f"{ROUTES}{coco['id']}/").json()["steps"]] == reordered
