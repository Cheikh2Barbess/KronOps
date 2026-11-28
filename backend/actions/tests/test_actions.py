"""Actions et alertes : qui fait quoi, pour quand, sur quel arret, lot ou produit.

Criteres d'acceptation :
- Admin, Production et Qualite creent une action : type, objet dans une liste fermee (precision seulement pour
  « Autre »), responsable de l'entreprise, echeance, priorite, liens facultatifs (arret, equipement, lot, produit) ;
- l'operateur appelle la maintenance ou la qualite depuis un arret en un clic : l'action est creee, a attribuer ;
- une action se commence, se termine avec un resultat code, ou s'annule avec un motif. Rien n'est efface ;
- le responsable fait avancer son action, un autre operateur non ;
- chaque changement passe au journal d'audit avec un evenement ;
- les alertes (produit sous la cible, arret en cours trop long, lot bloque, action en retard) sont calculees et
  disent si une action ouverte les couvre ;
- le tableau de bord montre les actions ouvertes et les alertes, en retard en rouge ;
- une entreprise ne voit jamais les actions d'une autre (404).
"""

import datetime

from django.utils import timezone

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from events.models import OutboxEvent
from lots.tests.conftest import client_for
from tenants.models import User

URL = "/api/v1/actions/"
STOPS = "/api/v1/production/stops/"


def today(days=0):
    return (timezone.localdate() + datetime.timedelta(days=days)).isoformat()


def create(client, **extra):
    data = {"action_type": "maintenance", "subject_code": "reparer_equipement", "priority": "haute",
            "due_date": today(1), **extra}
    return client.post(URL, data, format="json")


def ongoing_stop(client, equipment, hours=5):
    start = (timezone.now() - datetime.timedelta(hours=hours)).isoformat()
    response = client.post(STOPS, {"equipment": str(equipment.id), "cause_code": "panne_mecanique",
                                   "started_at": start}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_options_list_coded_types_subjects_and_people(client_a, admin_a):
    body = client_a.get(URL + "options/").json()
    assert {t["code"] for t in body["types"]} == {"maintenance", "qualite", "production", "approvisionnement"}
    subjects = {s["code"]: s for s in body["subjects"]}
    assert subjects["reparer_equipement"]["action_type"] == "maintenance"
    assert subjects["autre"]["action_type"] is None
    assert str(admin_a.id) in {u["id"] for u in body["people"]}


def test_manager_creates_an_action_linked_to_a_stop(tenant_a, client_a, admin_a, orchard):
    stop = ongoing_stop(client_a, orchard["dryer1"])
    response = create(client_a, responsible=str(admin_a.id), line_stop=stop["id"])
    assert response.status_code == 201, response.json()
    action = response.json()
    assert action["status"] == "ouverte" and action["subject"] == "Réparer l'équipement"
    assert action["equipment"]["code"] == "SEC-1"  # recopie depuis l'arret
    assert action["late"] is False
    with tenant_context(tenant_a.id):
        assert AuditLog.objects.filter(entity_type="actions.action").count() == 1
        assert OutboxEvent.objects.filter(event_type="actions.action_created").count() == 1


def test_subject_must_match_type_and_other_needs_a_comment(client_a):
    assert create(client_a, subject_code="recontroler_lot").status_code == 400
    assert create(client_a, subject_code="inconnu").status_code == 400
    response = create(client_a, subject_code="autre")
    assert response.status_code == 400 and "comment" in response.json()
    assert create(client_a, subject_code="autre", comment="Changer le joint de porte").status_code == 201


def test_due_date_cannot_be_in_the_past(client_a):
    assert create(client_a, due_date=today(-1)).status_code == 400


def test_operator_calls_maintenance_from_a_stop(tenant_a, client_a, orchard):
    operator = client_for(make_user(tenant_a, "op_call", role=User.Role.OPERATEUR))
    stop = ongoing_stop(client_a, orchard["dryer1"])
    response = operator.post(URL + "call/", {"line_stop": stop["id"], "action_type": "maintenance"}, format="json")
    assert response.status_code == 201, response.json()
    call = response.json()
    assert call["origin"] == "appel_poste" and call["responsible"] is None and call["priority"] == "haute"
    assert call["due_date"] == today()
    # Un second appel du meme service sur le meme arret est refuse : l'appel est deja en attente.
    again = operator.post(URL + "call/", {"line_stop": stop["id"], "action_type": "maintenance"}, format="json")
    assert again.status_code == 400
    assert operator.post(URL + "call/", {"line_stop": stop["id"], "action_type": "qualite"},
                         format="json").status_code == 201
    # L'operateur ne cree pas d'action ordinaire et n'en attribue pas.
    assert create(operator).status_code == 403
    assert operator.post(f"{URL}{call['id']}/assign/", {"responsible": None}, format="json").status_code == 403


def test_lifecycle_start_close_and_nothing_is_deleted(tenant_a, client_a, admin_a):
    action = create(client_a, responsible=str(admin_a.id)).json()
    started = client_a.post(f"{URL}{action['id']}/start/", {}, format="json")
    assert started.status_code == 200 and started.json()["status"] == "en_cours"
    closed = client_a.post(f"{URL}{action['id']}/close/", {"result_code": "resolu"}, format="json")
    assert closed.status_code == 200 and closed.json()["status"] == "terminee"
    assert closed.json()["result"] == "Résolu"
    again = client_a.post(f"{URL}{action['id']}/close/", {"result_code": "resolu"}, format="json")
    assert again.status_code == 400
    other = create(client_a).json()
    cancelled = client_a.post(f"{URL}{other['id']}/cancel/", {"reason_code": "doublon"}, format="json")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "annulee"
    assert len(client_a.get(URL, {"status": "all"}).json()) == 2
    assert client_a.delete(f"{URL}{other['id']}/").status_code == 405


def test_responsible_moves_own_action_but_not_someone_elses(tenant_a, client_a):
    operator = make_user(tenant_a, "op_resp", role=User.Role.OPERATEUR)
    other = client_for(make_user(tenant_a, "op_other", role=User.Role.OPERATEUR))
    action = create(client_a, responsible=str(operator.id)).json()
    assert other.post(f"{URL}{action['id']}/start/", {}, format="json").status_code == 403
    mine = client_for(operator)
    assert mine.post(f"{URL}{action['id']}/start/", {}, format="json").status_code == 200
    assert mine.post(f"{URL}{action['id']}/close/", {"result_code": "partiel"}, format="json").status_code == 200


def test_late_action_and_alerts(tenant_a, client_a, admin_a, orchard):
    stop = ongoing_stop(client_a, orchard["dryer1"], hours=5)
    alerts = client_a.get(URL + "alerts/").json()
    long_stop = next(a for a in alerts if a["code"] == "ongoing_stop")
    assert long_stop["status"] == "bad" and long_stop["open_action"] is None
    assert long_stop["create"]["line_stop"] == stop["id"]
    create(client_a, responsible=str(admin_a.id), line_stop=stop["id"])
    covered = next(a for a in client_a.get(URL + "alerts/").json() if a["code"] == "ongoing_stop")
    assert covered["open_action"]["responsible"] == (admin_a.get_full_name() or admin_a.username)
    # Une action dont l'echeance est passee devient une alerte rouge.
    with tenant_context(tenant_a.id):
        from actions.models import Action
        Action.objects.update(due_date=timezone.localdate() - datetime.timedelta(days=2))
    late = [a for a in client_a.get(URL + "alerts/").json() if a["code"] == "late_action"]
    assert late and late[0]["status"] == "bad"


def test_dashboard_tiles_for_actions_and_alerts(tenant_a, client_a, admin_a, orchard):
    ongoing_stop(client_a, orchard["dryer1"], hours=5)
    create(client_a, responsible=str(admin_a.id))
    for role in (User.Role.ADMIN, User.Role.PRODUCTION, User.Role.QUALITE, User.Role.OPERATEUR, User.Role.LECTURE):
        client = client_a if role == User.Role.ADMIN else client_for(make_user(tenant_a, f"t_{role}", role=role))
        tiles = {t["code"]: t for t in client.get("/api/v1/dashboard/").json()["tiles"]}
        assert "actions" in tiles and "alerts" in tiles
    tiles = {t["code"]: t for t in client_a.get("/api/v1/dashboard/").json()["tiles"]}
    assert tiles["actions"]["value"] == 1 and tiles["alerts"]["status"] == "bad"
    assert tiles["actions"]["link"]["href"] == "/actions"


def test_reader_only_reads(tenant_a, client_a):
    reader = client_for(make_user(tenant_a, "lect_act", role=User.Role.LECTURE))
    create(client_a)
    assert reader.get(URL).status_code == 200
    assert create(reader).status_code == 403


def test_isolation_between_companies(client_a, client_b, admin_a, admin_b, orchard):
    action = create(client_a, responsible=str(admin_a.id)).json()
    assert client_b.get(URL, {"status": "all"}).json() == []
    assert client_b.post(f"{URL}{action['id']}/start/", {}, format="json").status_code == 404
    assert client_b.get(f"{URL}{action['id']}/").status_code == 404
    assert client_a.get(f"{URL}{action['id']}/").status_code == 200
    # Un responsable ou un arret d'une autre entreprise est introuvable.
    assert create(client_b, responsible=str(admin_a.id)).status_code == 400
    stop = ongoing_stop(client_a, orchard["dryer1"])
    assert create(client_b, line_stop=stop["id"]).status_code == 400
    assert client_b.get(URL + "alerts/").json() == []
