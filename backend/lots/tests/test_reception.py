"""Reception (US-04, partie API) : un lot est cree avec un mouvement d'entree, dans l'unite de base."""

from decimal import Decimal

from audit.models import AuditLog
from core.tenancy import tenant_context
from events.models import OutboxEvent
from lots.models import Lot, Movement

URL = "/api/v1/lots/receptions/"


def test_reception_creates_lot_and_entry_movement(operator_client, reception_payload, tenant_a):
    response = operator_client.post(URL, reception_payload, format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "disponible"
    assert Decimal(body["balance"]) == Decimal("250")  # 10 sacs x 25 kg
    assert body["code"].startswith("MP-FAR-")
    with tenant_context(tenant_a.id):
        lot = Lot.objects.get(pk=body["id"])
        movement = Movement.objects.get(lot=lot)
        assert movement.movement_type == "reception"
        assert movement.quantity == Decimal("250.000")
        assert movement.partner_id is not None
        assert AuditLog.objects.filter(entity_id=lot.id, action="create").exists()
        assert OutboxEvent.objects.filter(event_type="lot.created").exists()


def test_quantity_in_base_unit(operator_client, reception_payload):
    reception_payload.update(quantity="12.5", unit="kg")
    response = operator_client.post(URL, reception_payload, format="json")
    assert Decimal(response.json()["balance"]) == Decimal("12.5")


def test_unknown_unit_is_refused(operator_client, reception_payload):
    reception_payload["unit"] = "carton"
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400


def test_quantity_must_be_positive_with_3_decimals_max(operator_client, reception_payload):
    reception_payload.update(unit="kg", quantity="0")
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400
    reception_payload["quantity"] = "1.0001"
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400


def test_lot_codes_are_unique_and_sequential(operator_client, reception_payload):
    first = operator_client.post(URL, reception_payload, format="json").json()["code"]
    second = operator_client.post(URL, reception_payload, format="json").json()["code"]
    assert first != second


def test_supplier_must_be_a_supplier(operator_client, reception_payload, ref_a):
    reception_payload["supplier"] = str(ref_a["customer"].id)
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400


def test_raw_material_needs_expiry_date(operator_client, reception_payload):
    del reception_payload["expiry_date"]
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400


def test_refrigerated_article_needs_temperature(operator_client, reception_payload, ref_a):
    reception_payload.update(article=str(ref_a["milk"].id), unit="l", date_type="dlc")
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400
    reception_payload["temperature_c"] = "3.5"
    assert operator_client.post(URL, reception_payload, format="json").status_code == 201


def test_non_conform_reception_creates_blocked_lot(operator_client, reception_payload, tenant_a):
    # Motif choisi dans la meme liste que le blocage (regle « le moins de texte libre possible », 26/11).
    reception_payload.update(visual_ok=False, reason_code="emballage_abime", comment="sacs déchirés")
    body = operator_client.post(URL, reception_payload, format="json").json()
    assert body["status"] == "bloque"
    assert body["block_code"] == "emballage_abime"
    assert body["block_reason"] == "Réception non conforme : Emballage abîmé : sacs déchirés"
    assert body["reception_visual_ok"] is False
    with tenant_context(tenant_a.id):
        assert OutboxEvent.objects.filter(event_type="lot.blocked").exists()


def test_non_conform_reception_needs_a_coded_reason(operator_client, reception_payload):
    reception_payload["visual_ok"] = False
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400
    reception_payload["reason_code"] = "pas_dans_la_liste"
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400
    reception_payload["reason_code"] = "autre"  # « Autre » exige une precision
    assert operator_client.post(URL, reception_payload, format="json").status_code == 400
    reception_payload["comment"] = "odeur suspecte"
    body = operator_client.post(URL, reception_payload, format="json").json()
    assert body["block_reason"] == "Réception non conforme : odeur suspecte"


def test_conform_reception_ignores_the_reason(operator_client, reception_payload):
    reception_payload.update(visual_ok=True, reason_code="temperature")
    body = operator_client.post(URL, reception_payload, format="json").json()
    assert body["status"] == "disponible"
    assert body["block_code"] == ""


def test_paper_reentry_keeps_declared_date(operator_client, reception_payload):
    # Coupure reseau : ressaisie d'une fiche papier, avec la date reelle declaree.
    reception_payload["occurred_at"] = "2026-11-20T08:30:00Z"
    reception_payload["late_reason_code"] = "ressaisie_papier"
    body = operator_client.post(URL, reception_payload, format="json").json()
    movement = body["movements"][0]
    assert movement["occurred_at"].startswith("2026-11-20")
    assert movement["created_at"] != movement["occurred_at"]
    assert movement["late_reason_code"] == "ressaisie_papier"


def test_reader_cannot_receive(reader_client, reception_payload):
    assert reader_client.post(URL, reception_payload, format="json").status_code == 403


def test_article_of_other_tenant_cannot_be_received(client_b, reception_payload):
    # L'article et le fournisseur du client A sont invisibles pour B : refuse.
    assert client_b.post(URL, reception_payload, format="json").status_code == 400
