"""Tableau de bord par role : chiffres tires des donnees saisies, couleurs selon des seuils reglables par client.

Criteres d'acceptation :
- chaque role a son tableau de bord (le patron ne voit pas la meme chose que l'operateur ou la qualite) ;
- aucun chiffre invente : sans donnee, la tuile dit « vide » au lieu d'afficher zero ;
- vert, jaune, rouge selon des seuils par defaut, marques comme tels, que l'Admin peut changer ;
- une entreprise ne voit jamais les chiffres ni les seuils d'une autre.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from dashboard.indicators import BAD, HIGHER, LOWER, OK, WARN, status_for
from events.models import OutboxEvent
from lots.tests.conftest import client_for
from shipping.tests.test_shipments_and_recall import chain, qc_ok, run, ship  # noqa: F401 (fixture)
from tenants.models import User

URL = "/api/v1/dashboard/"
THRESHOLDS = "/api/v1/dashboard/thresholds/"


def tiles(client, **params):
    response = client.get(URL, params)
    assert response.status_code == 200, response.json()
    return {t["code"]: t for t in response.json()["tiles"]}


# Regle des couleurs -------------------------------------------------------------


@pytest.mark.parametrize("value, expected", [(96, OK), (95, OK), (90, WARN), (85, WARN), (84.9, BAD)])
def test_colour_rule_when_higher_is_better(value, expected):
    assert status_for(value, direction=HIGHER, green=Decimal("95"), red=Decimal("85")) == expected


@pytest.mark.parametrize("value, expected", [(0, OK), (2, WARN), (3, WARN), (4, BAD)])
def test_colour_rule_when_lower_is_better(value, expected):
    assert status_for(value, direction=LOWER, green=Decimal("0"), red=Decimal("3")) == expected


# Un tableau de bord par role ------------------------------------------------------


def test_each_role_has_its_own_dashboard(tenant_a, client_a):
    by_role = {User.Role.ADMIN: set(tiles(client_a))}
    for role in (User.Role.PRODUCTION, User.Role.QUALITE, User.Role.OPERATEUR, User.Role.LECTURE):
        by_role[role] = set(tiles(client_for(make_user(tenant_a, f"u_{role}", role=role))))
    assert len({frozenset(v) for v in by_role.values()}) == 5
    assert {"received", "shipped", "yields", "qc"} <= by_role[User.Role.ADMIN]
    assert {"moisture", "ready_without_qc"} <= by_role[User.Role.QUALITE]
    assert {"runs", "bottleneck", "wip"} <= by_role[User.Role.PRODUCTION]
    # L'operateur ne lit pas les expeditions (droits existants) : pas de tuile expedition.
    assert "shipped" not in by_role[User.Role.OPERATEUR] and "wip" in by_role[User.Role.OPERATEUR]
    # Le role Lecture ne voit pas les demandes de double validation.
    assert "approvals" not in by_role[User.Role.LECTURE]


def test_anonymous_is_refused():
    assert APIClient().get(URL).status_code in (401, 403)


def test_unknown_period_is_refused(client_a):
    assert client_a.get(URL, {"days": 12}).status_code == 400


def test_empty_company_shows_empty_tiles_not_zeros(client_a):
    found = tiles(client_a)
    for code in ("received", "produced", "shipped", "qc", "bottleneck"):
        assert found[code]["empty"] is True and found[code]["value"] is None
    # Etat actuel sans probleme : vert, pas vide.
    assert found["blocked"]["value"] == 0 and found["blocked"]["status"] == OK


# Chiffres tires des donnees -----------------------------------------------------


def test_figures_come_from_receptions_runs_checks_and_shipments(client_a, orchard, chain):
    c1 = chain["c1"]["output_lot_id"]
    assert ship(client_a, orchard, [(c1, "10")], bill_of_lading="BL-1").status_code == 201
    found = tiles(client_a)
    assert found["received"]["value"] == 2600
    assert found["produced"]["value"] == 195
    assert found["shipped"]["value"] == 100
    assert found["shipped"]["status"] == OK  # COI, plomb et BL saisis
    assert found["qc"]["value"] == 100 and found["qc"]["status"] == OK
    # Sechage 100 kg pour 1300 kg (7,69 %) et 95 pour 1300 (7,31 %) : dans la fourchette 5,5 a 7,7 %.
    assert found["yields"]["value"] == 100 and found["yields"]["status"] == OK
    assert "pour 1" in found["yields"]["subtitle"]
    assert found["organic"]["value"] == 100
    kinds = {d["kind"] for d in found["received"]["detail"]}
    assert {"line", "bars", "table"} <= kinds


def test_shipment_of_organic_product_without_inspection_certificate_is_red(client_a, orchard, chain):
    c1 = chain["c1"]["output_lot_id"]
    assert ship(client_a, orchard, [(c1, "10")], export_document_ref="").status_code == 201
    shipped = tiles(client_a)["shipped"]
    assert shipped["status"] == BAD
    assert "COI" in str(shipped["detail"][1]["rows"])


def test_blocked_lot_turns_the_tile_yellow_then_red(client_a, chain, tenant_a):
    for key in ("c1", "c2"):
        lot_id = chain[key]["output_lot_id"]
        response = client_a.post(f"/api/v1/lots/{lot_id}/quality-checks/", {"checks": {"humidite": "nok"}},
                                 format="json")
        assert response.status_code == 201
    blocked = tiles(client_a)["blocked"]
    assert blocked["value"] == 2 and blocked["status"] == WARN  # vert a 0, rouge au-dela de 3 (defaut)
    quality = tiles(client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE)))
    assert quality["qc"]["status"] == BAD  # 2 conformes sur 4


def test_bottleneck_is_the_step_with_the_longest_wait(client_a, orchard, receive_fresh):
    import datetime

    from django.utils import timezone

    fresh = receive_fresh(orchard["p_bio"], "1300")
    later = timezone.now() + datetime.timedelta(hours=1)
    # Le lot recu attend 1 heure avant le sechage : vert (defaut : vert jusqu'a 24 h).
    data = {"step": "sechage", "output_article": str(orchard["dried"].id), "output_quantity": "100",
            "inputs": [{"lot": str(fresh.id), "quantity": "1300"}],
            "started_at": later.isoformat(), "ended_at": later.isoformat()}
    response = client_a.post("/api/v1/production/runs/", data, format="json")
    if response.status_code != 201:  # une date future peut etre refusee : sans date, attente quasi nulle
        data.pop("started_at"), data.pop("ended_at")
        response = client_a.post("/api/v1/production/runs/", data, format="json")
    assert response.status_code == 201, response.json()
    bottleneck = tiles(client_a)["bottleneck"]
    assert bottleneck["status"] == OK and "Séchage" in bottleneck["value_label"]
    assert bottleneck["detail"][0]["bars"][0]["label"] == "Séchage"


def test_operator_sees_what_waits_for_the_next_step(tenant_a, orchard, receive_fresh):
    receive_fresh(orchard["p_bio"], "500")
    operator = client_for(make_user(tenant_a, "op_a", role=User.Role.OPERATEUR))
    response = operator.get(URL)
    assert response.json()["days"] == 7
    wip = {t["code"]: t for t in response.json()["tiles"]}["wip"]
    assert wip["value"] == 1 and wip["title"] == "À traiter"
    assert wip["detail"][1]["rows"][0][0] == "Réception"


# Seuils reglables par client --------------------------------------------------------


def test_thresholds_have_marked_defaults(client_a):
    rows = {r["code"]: r for r in client_a.get(THRESHOLDS).json()}
    assert rows["qc_conformity_pct"]["is_default"] is True
    assert Decimal(rows["qc_conformity_pct"]["green"]) == Decimal(rows["qc_conformity_pct"]["default_green"])


def test_admin_changes_a_threshold_and_the_colour_follows(client_a, chain, tenant_a):
    lot_id = chain["c1"]["output_lot_id"]
    client_a.post(f"/api/v1/lots/{lot_id}/quality-checks/", {"checks": {"humidite": "nok"}}, format="json")
    assert tiles(client_a)["blocked"]["status"] == WARN
    response = client_a.put(f"{THRESHOLDS}blocked_lots/", {"green": "1", "red": "5"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["is_default"] is False
    blocked = tiles(client_a)["blocked"]
    assert blocked["status"] == OK and blocked["threshold"]["is_default"] is False
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="dashboard.dashboardthreshold", action="create").exists()
        assert OutboxEvent.objects.filter(event_type="dashboard.threshold_changed").exists()
    # Retour a la valeur par defaut.
    reset = client_a.delete(f"{THRESHOLDS}blocked_lots/")
    assert reset.status_code == 200 and reset.json()["is_default"] is True
    assert tiles(client_a)["blocked"]["status"] == WARN


def test_inconsistent_threshold_is_refused(client_a):
    # Plus c'est haut, mieux c'est : le vert ne peut pas etre sous le rouge.
    response = client_a.put(f"{THRESHOLDS}qc_conformity_pct/", {"green": "80", "red": "90"}, format="json")
    assert response.status_code == 400
    assert client_a.put(f"{THRESHOLDS}qc_conformity_pct/", {"green": "120", "red": "90"}, format="json").status_code == 400
    assert client_a.put(f"{THRESHOLDS}inconnu/", {"green": "1", "red": "2"}, format="json").status_code == 404


@pytest.mark.parametrize("role", [User.Role.QUALITE, User.Role.PRODUCTION, User.Role.OPERATEUR, User.Role.LECTURE])
def test_only_admin_changes_thresholds(tenant_a, role):
    client = client_for(make_user(tenant_a, f"t_{role}", role=role))
    assert client.get(THRESHOLDS).status_code == 200
    assert client.put(f"{THRESHOLDS}blocked_lots/", {"green": "1", "red": "5"}, format="json").status_code == 403
    assert client.delete(f"{THRESHOLDS}blocked_lots/").status_code == 403


# Isolation entre entreprises -------------------------------------------------------


def test_isolation_figures_of_another_company_are_never_counted(client_a, client_b, chain):
    found = tiles(client_b)
    assert found["received"]["empty"] is True
    assert found["produced"]["empty"] is True
    assert found["stock"]["empty"] is True


def test_isolation_thresholds_are_per_company(client_a, client_b):
    assert client_a.put(f"{THRESHOLDS}blocked_lots/", {"green": "2", "red": "6"}, format="json").status_code == 200
    rows = {r["code"]: r for r in client_b.get(THRESHOLDS).json()}
    assert rows["blocked_lots"]["is_default"] is True
    # B remet « a zero » : ne touche pas au reglage de A.
    assert client_b.delete(f"{THRESHOLDS}blocked_lots/").status_code == 200
    rows_a = {r["code"]: r for r in client_a.get(THRESHOLDS).json()}
    assert rows_a["blocked_lots"]["is_default"] is False


# Comparaison avec la periode precedente ------------------------------------------------


def _receive_at(tenant, user, orchard, kg, days_ago):
    import datetime

    from django.utils import timezone

    from lots import services as lots

    with tenant_context(tenant.id):
        return lots.receive_lot(
            tenant_id=tenant.id, user=user, article=orchard["fresh"], supplier=orchard["p_bio"].producer,
            supplier_lot_code="", quantity=Decimal(kg), unit="kg", date_type="ddm",
            expiry_date=datetime.date.today() + datetime.timedelta(days=30), parcel=orchard["p_bio"],
            occurred_at=timezone.now() - datetime.timedelta(days=days_ago), late_reason_code="ressaisie_papier",
        )


def test_period_tile_gives_the_value_of_the_previous_period(client_a, tenant_a, admin_a, orchard):
    _receive_at(tenant_a, admin_a, orchard, "500", days_ago=2)
    _receive_at(tenant_a, admin_a, orchard, "800", days_ago=40)  # periode precedente (30 a 60 jours)
    _receive_at(tenant_a, admin_a, orchard, "9000", days_ago=70)  # hors des deux periodes
    received = tiles(client_a, days=30)["received"]
    assert received["value"] == 500
    assert received["previous"] == 800


def test_previous_period_without_data_is_empty_not_zero(client_a, tenant_a, admin_a, orchard):
    _receive_at(tenant_a, admin_a, orchard, "500", days_ago=2)
    received = tiles(client_a, days=30)["received"]
    assert received["value"] == 500 and received["previous"] is None


def test_current_state_tile_has_no_comparison(client_a, chain):
    # « Lots bloques » est un etat actuel : aucun historique stocke, donc aucune comparaison inventee.
    assert tiles(client_a)["blocked"]["previous"] is None


def test_curves_say_how_values_are_grouped(client_a, tenant_a, admin_a, orchard):
    _receive_at(tenant_a, admin_a, orchard, "500", days_ago=2)
    line = tiles(client_a, days=30)["received"]["detail"][0]
    assert line["kind"] == "line" and line["aggregate"] == "sum"


def test_isolation_previous_period_ignores_another_company(client_a, client_b, tenant_a, admin_a, orchard):
    _receive_at(tenant_a, admin_a, orchard, "800", days_ago=40)
    _receive_at(tenant_a, admin_a, orchard, "500", days_ago=2)
    received = tiles(client_b, days=30)["received"]
    assert received["value"] is None and received["previous"] is None
