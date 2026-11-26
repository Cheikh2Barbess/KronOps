"""US-20 Double validation : deblocage, destruction, rebut et ajustement de stock.

Regles du PRD (matrice des droits, cycle de vie du lot, tests obligatoires) :
- l'action n'est executee qu'apres la validation d'un 2e utilisateur, d'un role different du demandeur ;
- un utilisateur ne valide jamais sa propre demande ;
- deblocage et destruction : demandes par la Qualite (cycle de vie), le lot doit etre bloque ;
- rebut : Qualite, Production ou Operateur ; ajustement : Qualite ou Production ;
- validateurs : Admin, Qualite, Production.
"""

import datetime
from decimal import Decimal

import pytest

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from lots import selectors, services
from lots.models import Lot, Movement
from lots.tests.conftest import client_for
from tenants.models import User

URL = "/api/v1/approvals/"


@pytest.fixture
def users(tenant_a, admin_a):
    return {
        "admin": admin_a,
        "qualite": make_user(tenant_a, "qualite_a", role=User.Role.QUALITE),
        "qualite2": make_user(tenant_a, "qualite_a2", role=User.Role.QUALITE),
        "production": make_user(tenant_a, "production_a", role=User.Role.PRODUCTION),
        "operateur": make_user(tenant_a, "operateur_a", role=User.Role.OPERATEUR),
        "lecture": make_user(tenant_a, "lecture_a", role=User.Role.LECTURE),
    }


@pytest.fixture
def c(users):
    return {name: client_for(user) for name, user in users.items()}


@pytest.fixture
def lot(tenant_a, admin_a, ref_a):
    with tenant_context(tenant_a.id):
        return services.receive_lot(
            tenant_id=tenant_a.id, user=admin_a, article=ref_a["flour"], supplier=ref_a["supplier"],
            supplier_lot_code="F-1", quantity=Decimal("100"), unit="kg", date_type="ddm",
            expiry_date=datetime.date(2027, 6, 30),
        )


@pytest.fixture
def blocked_lot(tenant_a, admin_a, lot):
    with tenant_context(tenant_a.id):
        services.block_lot(tenant_id=tenant_a.id, user=admin_a, lot_id=lot.id, reason="Moisissures")
    return lot


def ask(client, action, lot, **extra):
    return client.post(URL, {"action": action, "lot": str(lot.id), "reason": "Contrôle", **extra}, format="json")


def lot_state(tenant_a, lot):
    with tenant_context(tenant_a.id):
        fresh = Lot.objects.get(pk=lot.pk)
        return fresh.status, selectors.lot_balance(lot.id)


# Deblocage ----------------------------------------------------------------


def test_release_waits_for_second_validation(c, tenant_a, blocked_lot):
    r = ask(c["qualite"], "release", blocked_lot)
    assert r.status_code == 201, r.json()
    assert r.json()["status"] == "pending"
    # Rien ne change tant que personne n'a valide.
    assert lot_state(tenant_a, blocked_lot)[0] == "bloque"
    r = c["production"].post(f"{URL}{r.json()['id']}/approve/", {}, format="json")
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "approved"
    assert r.json()["decided_by_username"] == "production_a"
    assert lot_state(tenant_a, blocked_lot)[0] == "disponible"
    with tenant_context(tenant_a.id):
        assert OutboxEvent.objects.filter(event_type="lot.released").exists()
        assert AuditLog.objects.filter(entity_id=blocked_lot.id, action="release").exists()
        assert AuditLog.objects.filter(entity_type="lots.approvalrequest", action="approve").exists()


def test_nobody_validates_own_request(c, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    r = c["qualite"].post(f"{URL}{request_id}/approve/", {}, format="json")
    assert r.status_code == 400
    assert "propre demande" in str(r.json())


def test_same_role_cannot_validate(c, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    r = c["qualite2"].post(f"{URL}{request_id}/approve/", {}, format="json")
    assert r.status_code == 400
    assert "autre rôle" in str(r.json())


def test_admin_can_validate(c, tenant_a, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    assert c["admin"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 200
    assert lot_state(tenant_a, blocked_lot)[0] == "disponible"


def test_only_quality_requests_release_or_destruction(c, blocked_lot):
    for role in ("production", "operateur", "admin"):
        assert ask(c[role], "release", blocked_lot).status_code == 403, role
        assert ask(c[role], "destroy", blocked_lot).status_code == 403, role


def test_release_needs_a_blocked_lot(c, lot):
    r = ask(c["qualite"], "release", lot)
    assert r.status_code == 400
    assert "bloqué" in str(r.json())


def test_operator_and_reader_cannot_validate(c, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    # L'operateur ne voit meme pas les demandes des autres : 404.
    assert c["operateur"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 404
    assert c["lecture"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 403


def test_reason_is_required(c, blocked_lot):
    r = c["qualite"].post(URL, {"action": "release", "lot": str(blocked_lot.id), "reason": " "}, format="json")
    assert r.status_code == 400


def test_one_pending_request_per_lot_and_action(c, blocked_lot):
    assert ask(c["qualite"], "release", blocked_lot).status_code == 201
    r = ask(c["qualite2"], "release", blocked_lot)
    assert r.status_code == 400
    assert "déjà" in str(r.json())


# Destruction --------------------------------------------------------------


def test_destruction_writes_off_the_balance(c, tenant_a, blocked_lot):
    request_id = ask(c["qualite"], "destroy", blocked_lot).json()["id"]
    assert c["admin"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 200
    status, balance = lot_state(tenant_a, blocked_lot)
    assert (status, balance) == ("detruit", 0)
    with tenant_context(tenant_a.id):
        m = Movement.objects.get(lot=blocked_lot, movement_type="destruction")
        assert m.quantity == Decimal("-100")
        assert OutboxEvent.objects.filter(event_type="lot.destroyed").exists()


def test_destroyed_lot_accepts_no_more_request(c, tenant_a, blocked_lot):
    request_id = ask(c["qualite"], "destroy", blocked_lot).json()["id"]
    c["admin"].post(f"{URL}{request_id}/approve/", {}, format="json")
    assert ask(c["production"], "scrap", blocked_lot, quantity="1").status_code == 400
    assert ask(c["qualite"], "release", blocked_lot).status_code == 400


# Rebut et ajustement ------------------------------------------------------


def test_operator_requests_scrap_validated_by_production(c, tenant_a, lot):
    r = ask(c["operateur"], "scrap", lot, quantity="12.5")
    assert r.status_code == 201, r.json()
    assert lot_state(tenant_a, lot)[1] == 100
    assert c["production"].post(f"{URL}{r.json()['id']}/approve/", {}, format="json").status_code == 200
    assert lot_state(tenant_a, lot)[1] == Decimal("87.5")
    with tenant_context(tenant_a.id):
        movement = Movement.objects.get(lot=lot, movement_type="rebut")
        # Enregistre a la validation, au nom du validateur. Le demandeur reste dans le motif.
        assert movement.user.username == "production_a"
        assert "operateur_a" in movement.reason


def test_scrap_is_allowed_on_a_blocked_lot(c, tenant_a, blocked_lot):
    request_id = ask(c["production"], "scrap", blocked_lot, quantity="10").json()["id"]
    assert c["qualite"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 200
    assert lot_state(tenant_a, blocked_lot) == ("bloque", 90)


def test_scrap_cannot_exceed_balance_even_at_validation(c, tenant_a, admin_a, lot):
    request_id = ask(c["production"], "scrap", lot, quantity="80").json()["id"]
    # Entre la demande et la validation, le stock a baisse.
    with tenant_context(tenant_a.id):
        services.record_exit(tenant_id=tenant_a.id, user=admin_a, lot_id=lot.id, movement_type="consommation",
                             quantity=Decimal("50"))
    r = c["qualite"].post(f"{URL}{request_id}/approve/", {}, format="json")
    assert r.status_code == 400
    assert lot_state(tenant_a, lot)[1] == 50


def test_adjustment_up_and_down(c, tenant_a, lot):
    down = ask(c["production"], "adjust", lot, quantity="-3").json()["id"]
    up = ask(c["qualite"], "adjust", lot, quantity="1.250").json()["id"]
    c["qualite"].post(f"{URL}{down}/approve/", {}, format="json")
    c["production"].post(f"{URL}{up}/approve/", {}, format="json")
    assert lot_state(tenant_a, lot)[1] == Decimal("98.250")


def test_operator_cannot_request_adjustment(c, lot):
    assert ask(c["operateur"], "adjust", lot, quantity="-1").status_code == 403


def test_quantity_rules(c, lot):
    assert ask(c["production"], "scrap", lot).status_code == 400  # quantite obligatoire
    assert ask(c["production"], "scrap", lot, quantity="-2").status_code == 400
    assert ask(c["production"], "adjust", lot, quantity="0").status_code == 400
    assert ask(c["production"], "scrap", lot, quantity="101").status_code == 400


def test_validated_scrap_cannot_be_undone_alone(c, tenant_a, users, lot):
    request_id = ask(c["production"], "scrap", lot, quantity="5").json()["id"]
    c["qualite"].post(f"{URL}{request_id}/approve/", {}, format="json")
    with tenant_context(tenant_a.id):
        movement_id = Movement.objects.get(lot=lot, movement_type="rebut").id
    r = c["admin"].post(f"/api/v1/movements/{movement_id}/reverse/", {"reason": "erreur"}, format="json")
    assert r.status_code == 400
    assert "ajustement" in str(r.json())


# Refus et annulation ------------------------------------------------------


def test_reject_needs_a_comment_and_changes_nothing(c, tenant_a, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    assert c["production"].post(f"{URL}{request_id}/reject/", {"comment": ""}, format="json").status_code == 400
    r = c["production"].post(f"{URL}{request_id}/reject/", {"comment": "Analyse labo pas reçue"}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert lot_state(tenant_a, blocked_lot)[0] == "bloque"
    # Une demande decidee ne se valide plus.
    assert c["admin"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 400


def test_requester_can_cancel_only_own_pending_request(c, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    assert c["production"].post(f"{URL}{request_id}/cancel/", {}, format="json").status_code == 403
    r = c["qualite"].post(f"{URL}{request_id}/cancel/", {}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# Lecture et isolation -----------------------------------------------------


def test_list_pending_requests(c, blocked_lot, lot):
    ask(c["qualite"], "release", blocked_lot)
    ask(c["operateur"], "scrap", lot, quantity="1")
    rows = c["production"].get(f"{URL}?status=pending").json()
    assert {r["action"] for r in rows} == {"release", "scrap"}
    assert all(r["lot_code"] for r in rows)
    # L'operateur ne voit que ses propres demandes.
    assert [r["action"] for r in c["operateur"].get(URL).json()] == ["scrap"]
    assert c["lecture"].get(URL).status_code == 403


def test_other_tenant_request_is_404(c, client_b, blocked_lot):
    request_id = ask(c["qualite"], "release", blocked_lot).json()["id"]
    assert client_b.post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 404
    assert client_b.get(f"{URL}{request_id}/").status_code == 404
    assert client_b.get(URL).json() == []
    # Lot d'un autre client : introuvable pour une demande.
    assert ask(client_b, "release", blocked_lot).status_code == 400


def test_operator_cannot_validate_even_a_visible_request(c, users, tenant_a, lot):
    # Cas limite : une demande visible par l'operateur (la sienne) reste refusee, et pour son role.
    request_id = ask(c["operateur"], "scrap", lot, quantity="1").json()["id"]
    assert c["operateur"].post(f"{URL}{request_id}/approve/", {}, format="json").status_code == 403
