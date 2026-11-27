"""Annulation d'une declaration : contre-mouvements, lot produit bloque, motif code, trace dans l'audit."""

from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from lots import selectors as lot_selectors
from production.models import RunCancellation
from tenants.models import User

URL = "/api/v1/production/runs/"


def dry(client, orchard, lot, qty, kg):
    data = {"step": "sechage", "equipment": str(orchard["dryer1"].id), "output_article": str(orchard["dried"].id),
            "output_quantity": kg, "inputs": [{"lot": str(lot.id), "quantity": qty}]}
    response = client.post(URL, data, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def cancel(client, run_id, code="mauvaise_quantite", comment=""):
    return client.post(f"{URL}{run_id}/cancel/", {"reason_code": code, "comment": comment}, format="json")


def test_cancel_gives_the_stock_back_and_blocks_the_output(client_a, orchard, receive_fresh, tenant_a):
    fresh = receive_fresh(orchard["p_bio"], "1300")
    run = dry(client_a, orchard, fresh, "1300", "90")
    response = cancel(client_a, run["id"])
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["cancelled"]["reason"] == "Mauvaise quantité"
    with tenant_context(tenant_a.id):
        assert lot_selectors.lot_or_404(lot_id=fresh.id).balance == Decimal("1300")
        output = lot_selectors.lot_or_404(lot_id=run["output_lot_id"])
        assert output.balance == 0 and output.status == "bloque"
        assert output.block_code == "declaration_annulee"
        assert AuditLog.objects.filter(action="cancel", entity_id=run["id"]).exists()
    # Le bilan matiere ne compte plus la declaration annulee.
    assert client_a.get("/api/v1/production/balance/").json()["runs"] == []
    # La matiere rendue peut etre redeclaree correctement.
    dry(client_a, orchard, fresh, "1300", "95")


def test_cannot_cancel_twice_or_once_the_output_was_used(client_a, orchard, receive_fresh):
    fresh = receive_fresh(orchard["p_bio"], "2600")
    run = dry(client_a, orchard, fresh, "1300", "90")
    assert cancel(client_a, run["id"]).status_code == 200
    assert cancel(client_a, run["id"]).status_code == 400
    used = dry(client_a, orchard, fresh, "1300", "90")
    pack = {"step": "conditionnement", "output_article": str(orchard["carton"].id), "output_quantity": "80",
            "inputs": [{"lot": used["output_lot_id"], "quantity": "80"}]}
    assert client_a.post(URL, pack, format="json").status_code == 201
    refused = cancel(client_a, used["id"])
    assert refused.status_code == 400 and "a déjà servi" in refused.json()["run"][0]


def test_other_reason_needs_a_comment(client_a, orchard, receive_fresh):
    run = dry(client_a, orchard, receive_fresh(orchard["p_bio"], "1300"), "1300", "90")
    assert cancel(client_a, run["id"], code="autre").status_code == 400
    assert cancel(client_a, run["id"], code="pas_dans_la_liste").status_code == 400
    assert cancel(client_a, run["id"], code="autre", comment="Mauvais séchoir").status_code == 200


def test_cancellations_are_append_only(client_a, orchard, receive_fresh, tenant_a):
    run = dry(client_a, orchard, receive_fresh(orchard["p_bio"], "1300"), "1300", "90")
    cancel(client_a, run["id"])
    with tenant_context(tenant_a.id):
        with pytest.raises(DatabaseError), transaction.atomic():
            RunCancellation.objects.all().delete()


def test_operator_cannot_cancel(tenant_a, client_a, orchard, receive_fresh):
    from rest_framework.test import APIClient

    run = dry(client_a, orchard, receive_fresh(orchard["p_bio"], "1300"), "1300", "90")
    operator = APIClient()
    operator.force_authenticate(make_user(tenant_a, "op", role=User.Role.OPERATEUR))
    assert cancel(operator, run["id"]).status_code == 403


def test_isolation_other_company(client_a, client_b, orchard, receive_fresh):
    run = dry(client_a, orchard, receive_fresh(orchard["p_bio"], "1300"), "1300", "90")
    assert cancel(client_b, run["id"]).status_code == 404
