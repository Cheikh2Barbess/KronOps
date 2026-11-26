"""Row-Level Security sur la table des utilisateurs (tenants_user).

La base elle-meme cache les comptes des autres entreprises, meme si le code oublie de filtrer.
La connexion et la session passent par des fonctions SQL dediees (voir la migration
tenants/0003), seules capables de retrouver un compte avant de connaitre son entreprise.
"""

import uuid

import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.test import override_settings
from rest_framework.test import APIClient

from conftest import PASSWORD, make_user
from core.tenancy import platform_user_context, tenant_context
from tenants import selectors
from tenants.models import Tenant, User


def login(client, username, password=PASSWORD):
    return client.post("/api/v1/auth/login/", {"username": username, "password": password}, format="json")


# Isolation par la base


def test_no_context_means_no_user_rows(admin_a, admin_b):
    assert User.objects.count() == 0


def test_database_hides_users_of_other_tenant_even_without_filter(admin_a, admin_b, tenant_a):
    with tenant_context(tenant_a.id):
        assert list(User.objects.values_list("username", flat=True)) == ["admin_a"]


def test_cannot_create_a_user_in_another_tenant(tenant_a, tenant_b):
    with pytest.raises(DatabaseError):
        with tenant_context(tenant_a.id):
            User.objects.create_user(username="intrus", password=PASSWORD, tenant=tenant_b)


def test_cannot_modify_a_user_of_another_tenant(tenant_a, admin_b):
    with tenant_context(tenant_a.id):
        assert User.objects.filter(pk=admin_b.pk).update(role=User.Role.LECTURE) == 0
    with tenant_context(admin_b.tenant_id):
        assert User.objects.get(pk=admin_b.pk).role == User.Role.ADMIN


def test_cannot_move_a_user_to_another_tenant(admin_a, tenant_a, tenant_b):
    with pytest.raises(DatabaseError):
        with tenant_context(tenant_a.id):
            User.objects.filter(pk=admin_a.pk).update(tenant=tenant_b)


def test_platform_accounts_are_invisible_to_companies(tenant_a, admin_a):
    staff = make_platform_staff()
    with tenant_context(tenant_a.id):
        assert not User.objects.filter(pk=staff.pk).exists()


def test_auth_functions_are_not_callable_by_public():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.proname, has_function_privilege('public', p.oid, 'EXECUTE') FROM pg_proc p "
            "WHERE p.proname LIKE 'auth\\_%%'"
        )
        rows = dict(cursor.fetchall())
    assert set(rows) == {"auth_user_by_username", "auth_user_by_id", "auth_username_taken"}
    assert not any(rows.values())


# Connexion et session : vraie session par cookie, pas de force_authenticate


def test_login_then_session_works_without_any_context(admin_a):
    client = APIClient()
    assert login(client, "admin_a").status_code == 200
    me = client.get("/api/v1/auth/me/")
    assert me.status_code == 200
    assert me.json()["username"] == "admin_a"


def test_login_records_last_login(admin_a, tenant_a):
    assert login(APIClient(), "admin_a").status_code == 200
    with tenant_context(tenant_a.id):
        assert User.objects.get(pk=admin_a.pk).last_login is not None


def test_session_only_sees_own_company_users(admin_a, admin_b):
    client = APIClient()
    login(client, "admin_a")
    usernames = [u["username"] for u in client.get("/api/v1/users/").json()]
    assert usernames == ["admin_a"]
    assert client.get(f"/api/v1/users/{admin_b.pk}/").status_code == 404


def test_wrong_password_and_unknown_user_give_same_answer(admin_a):
    assert login(APIClient(), "admin_a", "faux-mot-de-passe").json() == {"detail": "Identifiants invalides."}
    assert login(APIClient(), "personne", "faux-mot-de-passe").json() == {"detail": "Identifiants invalides."}


def test_deactivated_user_cannot_log_in(tenant_a):
    user = make_user(tenant_a, "parti")
    with tenant_context(tenant_a.id):
        User.objects.filter(pk=user.pk).update(is_active=False)
    assert login(APIClient(), "parti").status_code == 400


@override_settings(PASSWORD_HASHERS=[
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.MD5PasswordHasher",
])
def test_old_password_hash_is_upgraded_at_login(admin_a, tenant_a):
    """Apres une mise a jour de Django, le hachage du mot de passe est renforce a la connexion."""
    with tenant_context(tenant_a.id):
        User.objects.filter(pk=admin_a.pk).update(password=make_password(PASSWORD, hasher="md5"))
    assert login(APIClient(), "admin_a").status_code == 200
    with tenant_context(tenant_a.id):
        assert User.objects.get(pk=admin_a.pk).password.startswith("pbkdf2_sha256$")


# Identifiants : uniques sur toute la plateforme, meme si les autres comptes sont invisibles


def test_username_of_another_company_is_refused(admin_a, admin_b):
    client = APIClient()
    client.force_authenticate(user=admin_a)
    response = client.post(
        "/api/v1/users/", {"username": "ADMIN_B", "password": PASSWORD, "role": "lecture"}, format="json"
    )
    assert response.status_code == 400
    assert "username" in response.json()


def test_selectors_find_accounts_across_companies(admin_a, admin_b):
    assert selectors.username_taken("Admin_B")
    assert not selectors.username_taken("inconnu")
    assert selectors.find_user_by_username("admin_b").tenant_id == admin_b.tenant_id
    assert selectors.find_user_by_username("inconnu") is None


# Commandes et administration de la plateforme


def test_create_tenant_then_create_user_commands():
    call_command("create_tenant", name="Entreprise C", admin="admin_c", password=PASSWORD)
    call_command("create_user", admin="admin_c", username="qualite_c", role="qualite", password=PASSWORD)
    tenant = Tenant.objects.get(name="Entreprise C")
    with tenant_context(tenant.id):
        assert sorted(User.objects.values_list("username", flat=True)) == ["admin_c", "qualite_c"]


def make_platform_staff():
    staff_id = uuid.uuid4()
    with platform_user_context(staff_id):
        return User.objects.create_superuser(id=staff_id, username="equipe", password=PASSWORD, email="")


def test_platform_staff_can_use_django_admin(tenant_a):
    staff = make_platform_staff()
    client = APIClient()
    response = client.post("/admin/login/", {"username": "equipe", "password": PASSWORD, "next": "/admin/"})
    assert response.status_code == 302
    page = client.get("/admin/tenants/tenant/")
    assert page.status_code == 200
    assert "Entreprise A" in page.content.decode()
    with platform_user_context(staff.pk):
        assert User.objects.get(pk=staff.pk).last_login is not None


def test_platform_staff_session_is_refused_by_business_api():
    make_platform_staff()
    client = APIClient()
    client.post("/admin/login/", {"username": "equipe", "password": PASSWORD, "next": "/admin/"})
    assert client.get("/api/v1/sites/").status_code == 403
