"""US-14 recherche aval et US-15 recherche amont, sur LotLink (requete recursive)."""

import datetime
from decimal import Decimal

import pytest
from django.db import DatabaseError

from core.tenancy import tenant_context
from lots import selectors, services
from lots.models import LotLink


@pytest.fixture
def genealogy(tenant_a, admin_a, ref_a):
    """Farine F1 + lait L1 -> biscuits P1. Farine F1 -> biscuits P2. P1 expedie au supermarche.

    Les OF n'existent pas encore : on utilise directement les briques create_lot et link_lots,
    que la declaration de production (US-08) appellera plus tard.
    """
    with tenant_context(tenant_a.id):
        def receive(article, qty, unit, code, temp=None):
            return services.receive_lot(
                tenant_id=tenant_a.id, user=admin_a, article=article, supplier=ref_a["supplier"],
                supplier_lot_code=code, quantity=Decimal(qty), unit=unit, date_type="dlc",
                expiry_date=datetime.date(2030, 1, 1), visual_ok=True, temperature_c=temp,
            )

        f1 = receive(ref_a["flour"], "100", "kg", "FOUR-FARINE-1")
        l1 = receive(ref_a["milk"], "50", "l", "FOUR-LAIT-1", temp=Decimal("4"))
        p1 = services.create_lot(
            tenant_id=tenant_a.id, user=admin_a, article=ref_a["biscuit"], quantity=Decimal("500"),
            entry_type="production", expiry_date=datetime.date(2027, 3, 1), date_type="dlc",
        )
        p2 = services.create_lot(
            tenant_id=tenant_a.id, user=admin_a, article=ref_a["biscuit"], quantity=Decimal("300"),
            entry_type="production", expiry_date=datetime.date(2027, 3, 2), date_type="dlc",
        )
        services.link_lots(tenant_id=tenant_a.id, user=admin_a, parent=f1, child=p1)
        services.link_lots(tenant_id=tenant_a.id, user=admin_a, parent=l1, child=p1)
        services.link_lots(tenant_id=tenant_a.id, user=admin_a, parent=f1, child=p2)
        services.record_exit(
            tenant_id=tenant_a.id, user=admin_a, lot_id=p1.id, movement_type="expedition",
            quantity=Decimal("200"), partner=ref_a["customer"],
        )
    return {"f1": f1, "l1": l1, "p1": p1, "p2": p2}


def test_downstream_from_supplier_lot_code(client_a, genealogy):
    response = client_a.get("/api/v1/traceability/downstream/?search=FOUR-FARINE-1")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert [o["id"] for o in body["origins"]] == [str(genealogy["f1"].id)]
    assert {lot["id"] for lot in body["lots"]} == {str(genealogy["p1"].id), str(genealogy["p2"].id)}
    shipment = body["shipments"][0]
    assert shipment["customer_name"] == "Supermarché"
    assert shipment["customer_address"] == "Plateau"
    assert Decimal(shipment["quantity"]) == Decimal("200")
    assert shipment["lot_id"] == str(genealogy["p1"].id)
    p1 = next(lot for lot in body["lots"] if lot["id"] == str(genealogy["p1"].id))
    assert Decimal(p1["balance"]) == Decimal("300")  # encore en stock


def test_upstream_from_finished_lot(client_a, genealogy):
    response = client_a.get(f"/api/v1/traceability/upstream/?lot={genealogy['p1'].id}")
    assert response.status_code == 200
    lots = response.json()["lots"]
    assert {lot["id"] for lot in lots} == {str(genealogy["f1"].id), str(genealogy["l1"].id)}
    assert {lot["supplier_name"] for lot in lots} == {"Moulins CI"}
    assert {lot["supplier_lot_code"] for lot in lots} == {"FOUR-FARINE-1", "FOUR-LAIT-1"}


def test_multi_level_genealogy_is_followed(client_a, genealogy, tenant_a, admin_a, ref_a):
    # Un semi-fini plus tard : la requete suit plusieurs niveaux sans changement.
    with tenant_context(tenant_a.id):
        p3 = services.create_lot(
            tenant_id=tenant_a.id, user=admin_a, article=ref_a["biscuit"], quantity=Decimal("10"),
            entry_type="production", expiry_date=datetime.date(2027, 3, 3), date_type="dlc",
        )
        services.link_lots(tenant_id=tenant_a.id, user=admin_a, parent=genealogy["p1"], child=p3)
    down = client_a.get(f"/api/v1/traceability/downstream/?lot={genealogy['f1'].id}").json()
    assert str(p3.id) in {lot["id"] for lot in down["lots"]}
    up = client_a.get(f"/api/v1/traceability/upstream/?lot={p3.id}").json()
    assert {str(genealogy["f1"].id), str(genealogy["l1"].id), str(genealogy["p1"].id)} <= {
        lot["id"] for lot in up["lots"]
    }


def test_unknown_search_returns_404(client_a, genealogy):
    assert client_a.get("/api/v1/traceability/downstream/?search=INCONNU").status_code == 404
    assert client_a.get("/api/v1/traceability/downstream/").status_code == 400


def test_lot_cannot_be_linked_to_itself(genealogy, tenant_a, admin_a):
    from rest_framework.exceptions import ValidationError

    with pytest.raises(ValidationError):
        with tenant_context(tenant_a.id):
            services.link_lots(tenant_id=tenant_a.id, user=admin_a, parent=genealogy["p1"], child=genealogy["p1"])


def test_lot_links_are_append_only(genealogy, tenant_a):
    with pytest.raises(DatabaseError):
        with tenant_context(tenant_a.id):
            LotLink.objects.all().delete()


def test_reader_can_search_operator_cannot(reader_client, operator_client, genealogy):
    url = f"/api/v1/traceability/downstream/?lot={genealogy['f1'].id}"
    assert reader_client.get(url).status_code == 200
    assert operator_client.get(url).status_code == 403


def test_other_tenant_sees_nothing(client_b, genealogy):
    assert client_b.get(f"/api/v1/traceability/downstream/?lot={genealogy['f1'].id}").status_code == 404
    assert client_b.get("/api/v1/traceability/downstream/?search=FOUR-FARINE-1").status_code == 404
    assert client_b.get(f"/api/v1/traceability/upstream/?lot={genealogy['p1'].id}").status_code == 404


def test_demo_command(admin_a, tenant_a):
    from django.core.management import call_command

    call_command("demo_tracabilite", admin=admin_a.username)
    with tenant_context(tenant_a.id):
        origins = selectors.find_origin_lots(search="DEMO-MOULIN-001")
        found, shipments = selectors.downstream(origins=origins)
    assert len(found) == 2 and len(shipments) == 1
