"""La liste des allergenes est une donnee de reference commune : l'application la lit, sans pouvoir la modifier."""

import pytest
from django.db import DatabaseError, transaction

from catalog.models import Allergen


def test_app_role_cannot_modify_allergen_list():
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            Allergen.objects.filter(code="gluten").update(name="falsifie")
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            Allergen.objects.create(regulation="UE_1169_2011", code="x", name="x", order=99)
