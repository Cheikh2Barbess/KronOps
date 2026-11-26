from rest_framework.test import APIClient

from conftest import PASSWORD, make_user
from tenants.models import User


def test_login_sets_httponly_session_cookie(admin_a):
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
    response = client.post(
        "/api/v1/auth/login/", {"username": "admin_a", "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=csrf
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert response.cookies["sessionid"]["httponly"]
    assert "token" not in response.json()


def test_login_without_csrf_token_is_refused(admin_a):
    client = APIClient(enforce_csrf_checks=True)
    response = client.post("/api/v1/auth/login/", {"username": "admin_a", "password": PASSWORD}, format="json")
    assert response.status_code == 403


def test_wrong_password_gives_generic_message(admin_a):
    response = APIClient().post("/api/v1/auth/login/", {"username": "admin_a", "password": "faux"}, format="json")
    assert response.status_code == 400
    assert response.json() == {"detail": "Identifiants invalides."}


def test_api_requires_authentication():
    assert APIClient().get("/api/v1/sites/").status_code == 403


def test_me_returns_current_user(client_a, admin_a):
    response = client_a.get("/api/v1/auth/me/")
    assert response.status_code == 200
    assert response.json()["username"] == "admin_a"


def test_operator_cannot_create_referential(tenant_a):
    operator = make_user(tenant_a, "operateur_a", role=User.Role.OPERATEUR)
    client = APIClient()
    client.force_authenticate(user=operator)
    assert client.post("/api/v1/sites/", {"name": "X"}, format="json").status_code == 403
    assert client.get("/api/v1/sites/").status_code == 403


def test_reader_can_list_but_not_create(tenant_a):
    reader = make_user(tenant_a, "lecture_a", role=User.Role.LECTURE)
    client = APIClient()
    client.force_authenticate(user=reader)
    assert client.get("/api/v1/sites/").status_code == 200
    assert client.post("/api/v1/sites/", {"name": "X"}, format="json").status_code == 403
