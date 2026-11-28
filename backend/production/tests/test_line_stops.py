"""Arrets de ligne : un equipement a l'arret, avec une cause choisie dans une liste codee.

Criteres d'acceptation :
- l'operateur, la production ou l'admin declare un arret (equipement, cause, debut, fin ou « en cours ») ;
- la cause vient d'une liste fermee, une precision n'est demandee que pour « Autre » ;
- chaque cause est classee planifiee (nettoyage, maintenance preventive) ou non planifiee (panne, coupure) ;
- un arret en cours se termine une seule fois, un equipement n'a qu'un arret en cours ;
- une erreur se corrige par une annulation avec motif (Admin, Production), jamais par un effacement ;
- chaque action passe au journal d'audit avec un evenement ;
- une entreprise ne voit jamais les arrets d'une autre (404).
"""

import datetime

import pytest
from django.utils import timezone

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from lots.tests.conftest import client_for
from production.models import LineStop
from tenants.models import User

URL = "/api/v1/production/stops/"


def declare(client, equipment, cause="panne_mecanique", **extra):
    data = {"equipment": str(equipment.id), "cause_code": cause, **extra}
    return client.post(URL, data, format="json")


def iso(dt):
    return dt.isoformat()


def test_options_list_coded_causes_with_planned_flag(client_a, orchard):
    response = client_a.get(URL + "options/")
    assert response.status_code == 200
    causes = {c["code"]: c for c in response.json()["causes"]}
    assert causes["coupure_courant"]["planned"] is False
    assert causes["nettoyage_changement"]["planned"] is True
    assert "autre" in causes
    assert {e["code"] for e in response.json()["equipment"]} == {"SEC-1", "SEC-2"}


def test_operator_declares_an_ongoing_stop_then_ends_it(tenant_a, orchard):
    operator = client_for(make_user(tenant_a, "op_stop", role=User.Role.OPERATEUR))
    start = timezone.now() - datetime.timedelta(hours=2)
    response = declare(operator, orchard["dryer1"], "coupure_courant", started_at=iso(start))
    assert response.status_code == 201, response.json()
    stop = response.json()
    assert stop["ongoing"] is True and stop["planned"] is False and stop["cause_label"] == "Coupure de courant"
    # Un seul arret en cours par equipement.
    again = declare(operator, orchard["dryer1"], "panne_mecanique")
    assert again.status_code == 400
    end = operator.post(f"{URL}{stop['id']}/end/", {}, format="json")
    assert end.status_code == 200, end.json()
    assert end.json()["ongoing"] is False and end.json()["duration_hours"] >= 1.9
    assert operator.post(f"{URL}{stop['id']}/end/", {}, format="json").status_code == 400
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="production.linestop").count() == 2
        assert OutboxEvent.objects.filter(event_type__in=["production.stop_declared", "production.stop_ended"]).count() == 2


def test_stop_with_start_and_end_after_the_fact(client_a, orchard):
    end = timezone.now() - datetime.timedelta(hours=1)
    start = end - datetime.timedelta(hours=3)
    response = declare(client_a, orchard["dryer2"], "nettoyage_changement", started_at=iso(start), ended_at=iso(end))
    assert response.status_code == 201, response.json()
    assert response.json()["planned"] is True and response.json()["duration_hours"] == 3


@pytest.mark.parametrize("payload, field", [
    ({"cause_code": "inconnu"}, "cause_code"),
    ({"cause_code": "autre"}, "comment"),
])
def test_cause_comes_from_the_coded_list(client_a, orchard, payload, field):
    response = client_a.post(URL, {"equipment": str(orchard["dryer1"].id), **payload}, format="json")
    assert response.status_code == 400 and field in response.json()


def test_other_cause_needs_a_comment(client_a, orchard):
    response = declare(client_a, orchard["dryer1"], "autre", comment="Toit du séchoir endommagé par l'orage")
    assert response.status_code == 201
    assert response.json()["cause_label"] == "Toit du séchoir endommagé par l'orage"


def test_end_before_start_and_future_dates_are_refused(client_a, orchard):
    now = timezone.now()
    bad = declare(client_a, orchard["dryer1"], started_at=iso(now - datetime.timedelta(hours=1)),
                  ended_at=iso(now - datetime.timedelta(hours=2)))
    assert bad.status_code == 400
    future = declare(client_a, orchard["dryer1"], started_at=iso(now + datetime.timedelta(hours=3)))
    assert future.status_code == 400


def test_overlapping_stops_on_the_same_equipment_are_refused(client_a, orchard):
    now = timezone.now()
    first = declare(client_a, orchard["dryer1"], started_at=iso(now - datetime.timedelta(hours=5)),
                    ended_at=iso(now - datetime.timedelta(hours=3)))
    assert first.status_code == 201
    overlap = declare(client_a, orchard["dryer1"], started_at=iso(now - datetime.timedelta(hours=4)),
                      ended_at=iso(now - datetime.timedelta(hours=2)))
    assert overlap.status_code == 400
    # Un autre equipement au meme moment : accepte.
    other = declare(client_a, orchard["dryer2"], started_at=iso(now - datetime.timedelta(hours=4)),
                    ended_at=iso(now - datetime.timedelta(hours=2)))
    assert other.status_code == 201


def test_cancel_keeps_the_stop_visible_and_is_for_managers_only(tenant_a, client_a, orchard):
    stop = declare(client_a, orchard["dryer1"]).json()
    operator = client_for(make_user(tenant_a, "op_cancel", role=User.Role.OPERATEUR))
    assert operator.post(f"{URL}{stop['id']}/cancel/", {"reason_code": "erreur_saisie"}, format="json").status_code == 403
    response = client_a.post(f"{URL}{stop['id']}/cancel/", {"reason_code": "erreur_saisie"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["cancelled"]["reason"] == "Erreur de saisie"
    with tenant_context(tenant_a.id):
        assert LineStop.objects.filter(pk=stop["id"]).exists()
    listed = client_a.get(URL).json()
    assert listed[0]["cancelled"] is not None
    # Une fois annule, l'equipement peut recevoir un nouvel arret en cours.
    assert declare(client_a, orchard["dryer1"]).status_code == 201


def test_reader_role_cannot_declare(tenant_a, orchard):
    reader = client_for(make_user(tenant_a, "lecteur_stop", role=User.Role.LECTURE))
    assert declare(reader, orchard["dryer1"]).status_code == 403
    assert reader.get(URL).status_code == 200


def test_isolation_between_companies(client_a, client_b, orchard):
    stop = declare(client_a, orchard["dryer1"]).json()
    assert client_b.get(URL).json() == []
    assert client_b.post(f"{URL}{stop['id']}/end/", {}, format="json").status_code == 404
    assert client_b.post(f"{URL}{stop['id']}/cancel/", {"reason_code": "erreur_saisie"}, format="json").status_code == 404
    # L'equipement d'un autre client est introuvable.
    assert declare(client_b, orchard["dryer1"]).status_code == 400
