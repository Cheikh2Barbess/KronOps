"""Journal lisible (decision du proprietaire du 26/11/2026) : le journal stocke ne change pas (insertion seule),
seule la presentation s'enrichit. Chaque ligne dit de quoi il s'agit (code du lot, nom de l'article ou du
partenaire), dans quelle unite sont les quantites, et les identifiants cites sont traduits en noms."""

import datetime
from decimal import Decimal

from audit.tests.test_audit_api import client_for
from conftest import make_user
from core.tenancy import tenant_context
from lots import services
from lots.tests.conftest import ref_a  # noqa: F401  (fixture)
from tenants.models import User

URL = "/api/v1/audit/"


def receive(tenant_a, admin_a, ref):
    with tenant_context(tenant_a.id):
        return services.receive_lot(
            tenant_id=tenant_a.id, user=admin_a, article=ref["flour"], supplier=ref["supplier"],
            supplier_lot_code="F-1", quantity=Decimal("20"), unit="sac", date_type="ddm",
            expiry_date=datetime.date(2027, 6, 30), organic_status="conventionnel",
        )


def entries(client, **params):
    return client.get(URL, params).json()["results"]


def test_each_line_names_its_subject_and_unit(tenant_a, admin_a, ref_a):  # noqa: F811
    lot = receive(tenant_a, admin_a, ref_a)
    quality = client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE))
    by_type = {e["entity_type"]: e for e in entries(quality)}
    assert by_type["lots.lot"]["subject"] == f"{lot.code} · MP-FAR Farine"
    assert by_type["lots.lot"]["unit"] == "kg"
    assert by_type["lots.movement"]["subject"] == f"Réception · {lot.code}"
    assert by_type["lots.movement"]["unit"] == "kg"
    assert by_type["catalog.article"]["subject"] in {"MP-FAR Farine", "MP-LAI Lait", "PF-BIS Biscuit"}
    assert by_type["catalog.partner"]["subject"] in {"Moulins CI", "Supermarché"}
    assert by_type["catalog.unitconversion"]["subject"] == "sac · MP-FAR Farine"
    assert by_type["catalog.unitconversion"]["unit"] == "kg"


def test_identifiers_in_values_become_names(tenant_a, admin_a, ref_a):  # noqa: F811
    lot = receive(tenant_a, admin_a, ref_a)
    quality = client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE))
    line = next(e for e in entries(quality) if e["entity_type"] == "lots.lot")
    refs = line["refs"]
    assert refs[line["new_values"]["article_id"]] == "MP-FAR Farine"
    assert refs[line["new_values"]["supplier_id"]] == "Moulins CI"
    movement = next(e for e in entries(quality) if e["entity_type"] == "lots.movement")
    assert movement["refs"][movement["new_values"]["lot_id"]] == f"{lot.code} · MP-FAR Farine"


def test_reversal_names_the_counter_movement(tenant_a, admin_a, ref_a):  # noqa: F811
    lot = receive(tenant_a, admin_a, ref_a)
    with tenant_context(tenant_a.id):
        movement = lot.movements.get()
        services.reverse_movement(tenant_id=tenant_a.id, user=admin_a, movement_id=movement.id, reason_code="doublon")
    quality = client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE))
    cancel = entries(quality, action="cancel")[0]
    assert cancel["subject"] == f"Réception · {lot.code}"
    assert cancel["refs"][cancel["new_values"]["reversal_id"]] == f"Annulation · {lot.code}"


def test_names_of_another_company_never_leak(tenant_a, admin_a, ref_a, admin_b):  # noqa: F811
    receive(tenant_a, admin_a, ref_a)
    other = client_for(admin_b)
    for line in entries(other):
        assert "Farine" not in str(line)


def test_user_creation_names_the_new_user(tenant_a, admin_a):
    from tenants import services as tenant_services

    with tenant_context(tenant_a.id):
        tenant_services.create_user(tenant_id=tenant_a.id, user=admin_a, username="op1",
                                    password="motdepasse-test-123", role=User.Role.OPERATEUR)
    line = entries(client_for(admin_a), entity_type="tenants.user")[0]
    assert line["subject"] == "op1"
    assert line["new_values"]["username"] == "op1" and line["new_values"]["role"] == "operateur"
    assert "password" not in line["new_values"]
