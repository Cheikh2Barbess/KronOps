"""Commande demo_tracabilite : tout ou rien, et relancable apres un essai interrompu."""

import pytest
from django.core.management import CommandError, call_command

from catalog import services as catalog
from catalog.models import Article
from core.tenancy import tenant_context
from lots.models import Lot


def test_demo_creates_lots_once(admin_a, tenant_a):
    call_command("demo_tracabilite", admin=admin_a.username)
    with tenant_context(tenant_a.id):
        assert Lot.objects.filter(supplier_lot_code="DEMO-MOULIN-001").count() == 1
    with pytest.raises(CommandError, match="existent déjà"):
        call_command("demo_tracabilite", admin=admin_a.username)


def test_demo_reuses_articles_left_by_an_interrupted_run(admin_a, tenant_a):
    # Cas reel : la commande lancee pendant les migrations avait cree les articles puis echoue.
    with tenant_context(tenant_a.id):
        catalog.create_article(
            tenant_id=tenant_a.id, user=admin_a, code="DEMO-BIS", name="Biscuit", article_type="fini",
            base_unit="unite",
        )
    call_command("demo_tracabilite", admin=admin_a.username)
    with tenant_context(tenant_a.id):
        assert Article.objects.filter(code="DEMO-BIS").count() == 1
        assert Lot.objects.filter(article__code="DEMO-BIS").count() == 2


def test_demo_refuses_unknown_admin(db):
    with pytest.raises(CommandError, match="Aucun administrateur"):
        call_command("demo_tracabilite", admin="personne")
