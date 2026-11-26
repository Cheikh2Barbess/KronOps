"""Lots et mouvements : insertion seule, solde, blocage, contre-mouvement."""

from decimal import Decimal

import pytest
from django.db import DatabaseError

from core.tenancy import tenant_context
from lots import services
from lots.models import Movement

RECEPTION = "/api/v1/lots/receptions/"


@pytest.fixture
def lot(client_a, reception_payload):
    response = client_a.post(RECEPTION, reception_payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_lot_detail_shows_balance_and_movements(operator_client, lot):
    body = operator_client.get(f"/api/v1/lots/{lot['id']}/").json()
    assert Decimal(body["balance"]) == Decimal("250")
    assert [m["movement_type"] for m in body["movements"]] == ["reception"]
    assert body["article_code"] == "MP-FAR"
    assert body["supplier_name"] == "Moulins CI"


def test_lot_list_and_filters(operator_client, lot, reception_payload, client_a):
    client_a.post(RECEPTION, dict(reception_payload, supplier_lot_code="AUTRE"), format="json")
    assert len(operator_client.get("/api/v1/lots/").json()) == 2
    assert len(operator_client.get("/api/v1/lots/?search=F-2026-118").json()) == 1
    assert len(operator_client.get("/api/v1/lots/?status=bloque").json()) == 0


def test_movements_are_append_only_in_database(lot, tenant_a):
    with tenant_context(tenant_a.id):
        movement = Movement.objects.get(lot_id=lot["id"])
    for action in (
        lambda: Movement.objects.filter(pk=movement.pk).update(quantity=1),
        lambda: Movement.objects.filter(pk=movement.pk).delete(),
    ):
        with pytest.raises(DatabaseError):
            with tenant_context(tenant_a.id):
                action()


def test_lot_cannot_be_deleted_through_api(client_a, lot):
    assert client_a.delete(f"/api/v1/lots/{lot['id']}/").status_code == 405


def test_block_lot_with_reason(client_a, lot):
    url = f"/api/v1/lots/{lot['id']}/block/"
    assert client_a.post(url, {}, format="json").status_code == 400  # motif obligatoire
    response = client_a.post(url, {"reason": "Suspicion de contamination"}, format="json")
    assert response.status_code == 200
    assert response.json()["status"] == "bloque"
    assert client_a.post(url, {"reason": "encore"}, format="json").status_code == 400  # deja bloque


def test_operator_cannot_block(operator_client, lot):
    assert operator_client.post(f"/api/v1/lots/{lot['id']}/block/", {"reason": "x"}, format="json").status_code == 403


def test_reverse_reception_with_reason(client_a, lot):
    movement_id = lot["movements"][0]["id"]
    url = f"/api/v1/movements/{movement_id}/reverse/"
    assert client_a.post(url, {}, format="json").status_code == 400  # motif obligatoire
    response = client_a.post(url, {"reason": "Erreur de saisie"}, format="json")
    assert response.status_code == 201, response.json()
    detail = client_a.get(f"/api/v1/lots/{lot['id']}/").json()
    assert Decimal(detail["balance"]) == 0
    assert detail["depleted"] is True
    types = [m["movement_type"] for m in detail["movements"]]
    assert types == ["reception", "annulation"]
    # Un mouvement ne s'annule qu'une fois, et une annulation ne s'annule pas.
    assert client_a.post(url, {"reason": "encore"}, format="json").status_code == 400
    reversal_id = detail["movements"][1]["id"]
    assert client_a.post(f"/api/v1/movements/{reversal_id}/reverse/", {"reason": "x"}, format="json").status_code == 400


def test_cannot_reverse_reception_once_lot_was_used(client_a, lot, tenant_a, admin_a, ref_a):
    with tenant_context(tenant_a.id):
        services.record_exit(
            tenant_id=tenant_a.id, user=admin_a, lot_id=lot["id"], movement_type="consommation", quantity=Decimal("10")
        )
    movement_id = lot["movements"][0]["id"]
    response = client_a.post(f"/api/v1/movements/{movement_id}/reverse/", {"reason": "x"}, format="json")
    assert response.status_code == 400


def test_stock_never_goes_negative(lot, tenant_a, admin_a):
    from rest_framework.exceptions import ValidationError

    with pytest.raises(ValidationError):
        with tenant_context(tenant_a.id):
            services.record_exit(
                tenant_id=tenant_a.id, user=admin_a, lot_id=lot["id"], movement_type="consommation",
                quantity=Decimal("250.001"),
            )


def test_blocked_lot_cannot_leave(client_a, lot, tenant_a, admin_a):
    from rest_framework.exceptions import ValidationError

    client_a.post(f"/api/v1/lots/{lot['id']}/block/", {"reason": "Analyse en cours"}, format="json")
    with pytest.raises(ValidationError):
        with tenant_context(tenant_a.id):
            services.record_exit(
                tenant_id=tenant_a.id, user=admin_a, lot_id=lot["id"], movement_type="expedition",
                quantity=Decimal("1"),
            )


def test_expired_lot_cannot_leave(client_a, reception_payload, tenant_a, admin_a):
    from rest_framework.exceptions import ValidationError

    reception_payload.update(date_type="dlc", expiry_date="2020-01-01")
    lot = client_a.post(RECEPTION, reception_payload, format="json").json()
    assert lot["expired"] is True
    with pytest.raises(ValidationError):
        with tenant_context(tenant_a.id):
            services.record_exit(
                tenant_id=tenant_a.id, user=admin_a, lot_id=lot["id"], movement_type="consommation",
                quantity=Decimal("1"),
            )


# Isolation ---------------------------------------------------------------


def test_lot_of_other_tenant_is_404(client_b, lot):
    assert client_b.get(f"/api/v1/lots/{lot['id']}/").status_code == 404
    assert client_b.post(f"/api/v1/lots/{lot['id']}/block/", {"reason": "x"}, format="json").status_code == 404
    movement_id = lot["movements"][0]["id"]
    assert client_b.post(f"/api/v1/movements/{movement_id}/reverse/", {"reason": "x"}, format="json").status_code == 404
    assert client_b.get("/api/v1/lots/").json() == []
