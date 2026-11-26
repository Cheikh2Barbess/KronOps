"""Fiches et gestion des utilisateurs (demande du proprietaire du 26/11/2026, US-01 avancee).

- Fiche : nom, prenom, poste (liste fermee), telephone, e-mail, superieur, role.
- Visible par les responsables seulement (Admin, Qualite, Production). Ni Operateur ni Lecture :
  donnees personnelles, minimisation (loi ivoirienne 2013-450).
- Gestion (creer, modifier, desactiver) : Admin seulement. Tout est trace au journal, jamais le mot de passe.
- La table des utilisateurs est protegee par la RLS (migration tenants/0003), et chaque lecture filtre
  aussi par entreprise dans le code (404 sinon).
"""

import pytest
from rest_framework.test import APIClient

from audit.models import AuditLog
from conftest import make_user
from core.tenancy import tenant_context
from tenants.models import User

USERS = "/api/v1/users/"
DIRECTORY = "/api/v1/users/directory/"
PASSWORD = "Un-mot-de-passe-solide-2026"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def boss(tenant_a):
    u = make_user(tenant_a, "patron")
    u.first_name, u.last_name, u.job_title = "Awa", "Koné", "directeur"
    with tenant_context(tenant_a.id):
        u.save()
    return u


@pytest.fixture
def admin(boss):
    return client_for(boss)


def create(admin, **extra):
    payload = {
        "username": "op1", "password": PASSWORD, "first_name": "Yao", "last_name": "Kouassi",
        "job_title": "operateur_production", "phone": "0707070707", "email": "yao@example.com",
        "role": "operateur", **extra,
    }
    return admin.post(USERS, payload, format="json")


def test_admin_creates_a_user_with_a_full_card(admin, boss, tenant_a):
    r = create(admin, manager=str(boss.id))
    assert r.status_code == 201, r.json()
    card = r.json()
    assert card["full_name"] == "Yao Kouassi"
    assert card["job_title_label"] == "Opérateur de production"
    assert card["role_label"] == "Opérateur"
    assert card["manager"] == {"id": str(boss.id), "username": "patron", "full_name": "Awa Koné"}
    assert "password" not in card
    with tenant_context(tenant_a.id):
        new = User.objects.get(username="op1")
        assert new.tenant_id == tenant_a.id and new.check_password(PASSWORD)
        log = AuditLog.objects.get(entity_id=new.id, action="create")
    assert log.new_values["job_title"] == "operateur_production"
    assert "password" not in str(log.new_values)


def test_job_title_comes_from_the_list(admin):
    assert create(admin, job_title="chef supreme").status_code == 400
    assert create(admin, job_title="autre").status_code == 400  # precision obligatoire
    r = create(admin, job_title="autre", job_title_other="Hygiéniste")
    assert r.json()["job_title_label"] == "Hygiéniste"


def test_weak_password_and_duplicate_username_are_refused(admin):
    assert create(admin, password="123").status_code == 400
    assert create(admin).status_code == 201
    assert create(admin).status_code == 400


def test_admin_edits_and_deactivates(admin, boss, tenant_a):
    user_id = create(admin).json()["id"]
    r = admin.patch(f"{USERS}{user_id}/", {"phone": "0101010101", "manager": str(boss.id)}, format="json")
    assert r.status_code == 200, r.json()
    assert r.json()["phone"] == "0101010101"
    r = admin.patch(f"{USERS}{user_id}/", {"is_active": False}, format="json")
    assert r.json()["is_active"] is False
    with tenant_context(tenant_a.id):
        changes = AuditLog.objects.filter(entity_id=user_id, action="update").order_by("created_at")
        assert changes[0].old_values["phone"] == "0707070707" and changes[0].new_values["phone"] == "0101010101"
        assert changes[1].new_values["is_active"] is False
    # Un compte desactive ne se connecte plus.
    client = APIClient()
    r = client.post("/api/v1/auth/login/", {"username": "op1", "password": PASSWORD}, format="json")
    assert r.status_code in (400, 403)


def test_password_reset_is_logged_without_the_password(admin, tenant_a):
    user_id = create(admin).json()["id"]
    admin.patch(f"{USERS}{user_id}/", {"password": "Un-autre-mot-de-passe-2026"}, format="json")
    with tenant_context(tenant_a.id):
        assert User.objects.get(pk=user_id).check_password("Un-autre-mot-de-passe-2026")
        log = AuditLog.objects.filter(entity_id=user_id, action="update").get()
    assert log.new_values == {"password": "(modifié)"}


def test_admin_cannot_lock_themselves_out(admin, boss):
    assert admin.patch(f"{USERS}{boss.id}/", {"is_active": False}, format="json").status_code == 400
    assert admin.patch(f"{USERS}{boss.id}/", {"role": "qualite"}, format="json").status_code == 400


def test_manager_rules(admin, boss, tenant_a, tenant_b):
    stranger = make_user(tenant_b, "etranger")
    assert create(admin, manager=str(stranger.id)).status_code == 400  # autre entreprise
    user_id = create(admin, manager=str(boss.id)).json()["id"]
    assert admin.patch(f"{USERS}{user_id}/", {"manager": user_id}, format="json").status_code == 400  # soi-meme
    # Pas de boucle : le patron ne peut pas avoir pour superieur quelqu'un qui depend de lui.
    assert admin.patch(f"{USERS}{boss.id}/", {"manager": user_id}, format="json").status_code == 400


def test_only_admin_manages_users(tenant_a, admin):
    quality = client_for(make_user(tenant_a, "qualite1", role=User.Role.QUALITE))
    assert create(quality).status_code == 403
    user_id = create(admin).json()["id"]
    assert quality.patch(f"{USERS}{user_id}/", {"phone": "1"}, format="json").status_code == 403


def test_managers_see_cards_operators_do_not(tenant_a, admin, boss):
    user_id = create(admin, manager=str(boss.id)).json()["id"]
    for role in ("qualite", "production"):
        client = client_for(make_user(tenant_a, f"{role}1", role=role))
        assert client.get(f"{USERS}{user_id}/").json()["phone"] == "0707070707"
        names = {row["username"]: row["full_name"] for row in client.get(DIRECTORY).json()}
        assert names["op1"] == "Yao Kouassi" and names["patron"] == "Awa Koné"
    for role in ("operateur", "lecture"):
        client = client_for(make_user(tenant_a, f"{role}9", role=role))
        assert client.get(f"{USERS}{user_id}/").status_code == 403
        assert client.get(DIRECTORY).status_code == 403


def test_options_lists_for_the_form(admin, tenant_a):
    body = admin.get(f"{USERS}options/").json()
    assert {"code": "responsable_qualite", "label": "Responsable qualité"} in body["job_titles"]
    assert {"code": "operateur", "label": "Opérateur"} in body["roles"]
    # Les listes ne sont pas des donnees personnelles : la Qualite les lit pour traduire le journal.
    assert client_for(make_user(tenant_a, "qualite1", role="qualite")).get(f"{USERS}options/").status_code == 200
    assert client_for(make_user(tenant_a, "op9", role="operateur")).get(f"{USERS}options/").status_code == 403


def test_users_of_another_company_are_invisible(admin, tenant_b):
    stranger = make_user(tenant_b, "etranger")
    assert admin.get(f"{USERS}{stranger.id}/").status_code == 404
    assert admin.patch(f"{USERS}{stranger.id}/", {"phone": "1"}, format="json").status_code == 404
    assert "etranger" not in str(admin.get(USERS).json())
    assert "etranger" not in str(admin.get(DIRECTORY).json())


def test_journal_names_the_modified_user(admin):
    user_id = create(admin).json()["id"]
    admin.patch(f"{USERS}{user_id}/", {"phone": "0101010101"}, format="json")
    line = admin.get("/api/v1/audit/", {"action": "update", "entity_type": "tenants.user"}).json()["results"][0]
    assert line["subject"] == "op1"
