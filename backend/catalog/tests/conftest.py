import pytest
from rest_framework.test import APIClient

from catalog.models import Allergen
from conftest import make_user
from tenants.models import User


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def allergen_codes():
    return list(Allergen.objects.order_by("order").values_list("code", flat=True))


@pytest.fixture
def all_absent(allergen_codes):
    return {code: "absent" for code in allergen_codes}


@pytest.fixture
def client_b(admin_b):
    return client_for(admin_b)


@pytest.fixture
def quality_client(tenant_a):
    return client_for(make_user(tenant_a, "qualite_a", role=User.Role.QUALITE))


@pytest.fixture
def production_client(tenant_a):
    return client_for(make_user(tenant_a, "production_a", role=User.Role.PRODUCTION))


@pytest.fixture
def operator_client(tenant_a):
    return client_for(make_user(tenant_a, "operateur_a", role=User.Role.OPERATEUR))


@pytest.fixture
def flour_payload(all_absent):
    allergens = dict(all_absent, gluten="contient")
    return {
        "code": "MP-FAR-01",
        "name": "Farine de blé T55",
        "article_type": "matiere",
        "base_unit": "kg",
        "storage": "ambiant",
        "allergens": allergens,
    }


@pytest.fixture
def article_of_b(client_b, all_absent):
    response = client_b.post(
        "/api/v1/articles/",
        {"code": "MP-B", "name": "Sucre B", "article_type": "matiere", "base_unit": "kg", "allergens": all_absent},
        format="json",
    )
    assert response.status_code == 201, response.json()
    return response.json()
