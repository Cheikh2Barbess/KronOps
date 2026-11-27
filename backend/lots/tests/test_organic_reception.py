"""Reception : statut bio recopie de la parcelle, site (usine), saisie au moment du geste."""

import datetime
from django.utils import timezone

from core.tenancy import tenant_context
from lots.models import Lot
from tenants.models import Site

URL = "/api/v1/lots/receptions/"


def payload(orchard, parcel=None, **extra):
    data = {
        "article": str(orchard["fresh"].id), "supplier": str((parcel or orchard["p_bio"]).producer_id),
        "quantity": "5", "unit": "caisse", "date_type": "ddm",
        "expiry_date": (datetime.date.today() + datetime.timedelta(days=10)).isoformat(), "visual_ok": True,
    }
    if parcel is not None:
        data["parcel"] = str(parcel.id)
    data.update(extra)
    return data


def test_parcel_status_is_copied_on_the_lot(client_a, orchard):
    response = client_a.post(URL, payload(orchard, orchard["p_bio"]), format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["organic_status"] == "bio"
    assert response.json()["parcel_code"] == "P-BIO"


def test_later_parcel_change_does_not_rewrite_the_lot(client_a, orchard, tenant_a, admin_a):
    lot_id = client_a.post(URL, payload(orchard, orchard["p_bio"]), format="json").json()["id"]
    from catalog import services as catalog
    with tenant_context(tenant_a.id):
        catalog.update_parcel(tenant_id=tenant_a.id, user=admin_a, parcel=orchard["p_bio"],
                              organic_status="conventionnel")
        assert Lot.objects.get(pk=lot_id).organic_status == "bio"


def test_parcel_of_another_supplier_is_refused(client_a, orchard):
    data = payload(orchard, orchard["p_bio"], supplier=str(orchard["producer2"].id))
    response = client_a.post(URL, data, format="json")
    assert response.status_code == 400
    assert "parcel" in response.json()


def test_without_parcel_status_must_be_chosen(client_a, orchard):
    assert client_a.post(URL, payload(orchard), format="json").status_code == 400
    response = client_a.post(URL, payload(orchard, organic_status="conversion"), format="json")
    assert response.status_code == 201
    assert response.json()["organic_status"] == "conversion"


def test_status_cannot_contradict_the_parcel(client_a, orchard):
    response = client_a.post(URL, payload(orchard, orchard["p_conv"], organic_status="bio"), format="json")
    assert response.status_code == 400


def test_packaging_has_no_organic_status(client_a, orchard):
    data = {"article": str(orchard["box"].id), "supplier": str(orchard["producer"].id), "quantity": "100",
            "unit": "unite", "visual_ok": True, "organic_status": "bio"}
    response = client_a.post(URL, data, format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["organic_status"] == ""


def test_isolation_parcel_of_other_company_is_not_found(client_b, orchard, tenant_b, admin_b):
    from catalog import services as catalog
    from catalog.selectors import allergen_codes
    with tenant_context(tenant_b.id):
        art = catalog.create_article(tenant_id=tenant_b.id, user=admin_b, code="MGF", name="Mangue",
                                     article_type="matiere", base_unit="kg",
                                     allergens={c: "absent" for c in allergen_codes()})
        sup = catalog.create_partner(tenant_id=tenant_b.id, user=admin_b, name="F", is_supplier=True, address="x")
    data = {"article": str(art.id), "supplier": str(sup.id), "quantity": "5", "unit": "kg", "date_type": "ddm",
            "expiry_date": "2030-01-01", "parcel": str(orchard["p_bio"].id)}
    response = client_b.post(URL, data, format="json")
    assert response.status_code == 400
    assert response.json() == {"parcel": ["Introuvable."]}


# Saisie au moment du geste ---------------------------------------------------


def test_entry_without_date_takes_server_time(client_a, orchard, tenant_a):
    before = timezone.now()
    lot_id = client_a.post(URL, payload(orchard, orchard["p_bio"]), format="json").json()["id"]
    with tenant_context(tenant_a.id):
        movement = Lot.objects.get(pk=lot_id).movements.get()
        assert movement.occurred_at >= before
        assert movement.late_reason_code == ""


def test_late_entry_requires_a_coded_reason_and_is_flagged(client_a, orchard):
    old = (timezone.now() - datetime.timedelta(days=2)).isoformat()
    refused = client_a.post(URL, payload(orchard, orchard["p_bio"], occurred_at=old), format="json")
    assert refused.status_code == 400
    assert "late_reason_code" in refused.json()
    ok = client_a.post(URL, payload(orchard, orchard["p_bio"], occurred_at=old, late_reason_code="ressaisie_papier"),
                       format="json")
    assert ok.status_code == 201
    rows = client_a.get(URL).json()
    assert rows[0]["late"] is True
    assert rows[0]["late_reason_code"] == "ressaisie_papier"


def test_future_date_is_refused(client_a, orchard):
    future = (timezone.now() + datetime.timedelta(hours=3)).isoformat()
    assert client_a.post(URL, payload(orchard, orchard["p_bio"], occurred_at=future), format="json").status_code == 400


def test_recent_date_within_tolerance_is_not_late(client_a, orchard):
    recent = (timezone.now() - datetime.timedelta(minutes=30)).isoformat()
    response = client_a.post(URL, payload(orchard, orchard["p_bio"], occurred_at=recent), format="json")
    assert response.status_code == 201
    assert client_a.get(URL).json()[0]["late"] is False


# Plusieurs sites -----------------------------------------------------------------


def test_single_site_is_used_by_default(client_a, orchard, site_of_tenant_a):
    response = client_a.post(URL, payload(orchard, orchard["p_bio"]), format="json")
    assert response.json()["site_name"] == "Usine A"


def test_site_is_required_when_company_has_several(client_a, orchard, site_of_tenant_a, tenant_a):
    with tenant_context(tenant_a.id):
        second = Site.objects.create(tenant=tenant_a, name="Usine Nord")
    assert client_a.post(URL, payload(orchard, orchard["p_bio"]), format="json").status_code == 400
    response = client_a.post(URL, payload(orchard, orchard["p_bio"], site=str(second.id)), format="json")
    assert response.status_code == 201
    assert response.json()["site_name"] == "Usine Nord"


def test_isolation_site_of_other_company_is_not_found(client_a, orchard, site_of_tenant_b):
    response = client_a.post(URL, payload(orchard, orchard["p_bio"], site=str(site_of_tenant_b.id)), format="json")
    assert response.status_code == 400


def test_fresh_fruit_without_label_date_gets_a_ddm_from_shelf_life(tenant_a, admin_a, orchard):
    import datetime
    from decimal import Decimal

    from catalog import services as catalog
    from core.tenancy import tenant_context
    from lots import services as lots

    with tenant_context(tenant_a.id):
        catalog.update_article(tenant_id=tenant_a.id, user=admin_a, article=orchard["fresh"], shelf_life_days=7)
        lot = lots.receive_lot(
            tenant_id=tenant_a.id, user=admin_a, article=orchard["fresh"], supplier=orchard["producer"],
            supplier_lot_code="", quantity=Decimal("100"), unit="kg", parcel=orchard["p_bio"],
        )
    assert lot.date_type == "ddm"
    assert lot.expiry_date == lot.production_date + datetime.timedelta(days=7)
