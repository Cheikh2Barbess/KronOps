"""Donnees de demonstration de la tracabilite, pour essayer la recherche amont/aval sans ecran de saisie.

Les ordres de fabrication (US-06 a US-08) n'existent pas encore : la commande relie directement les lots
de matieres aux lots de biscuits avec la brique link_lots, comme le fera la declaration de production.
Tous les codes commencent par DEMO pour etre reconnaissables.
"""

import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from catalog import services as catalog
from catalog.models import Article
from catalog.selectors import allergen_codes
from core.tenancy import tenant_context
from lots import services
from tenants.models import User


class Command(BaseCommand):
    help = "Cree des lots de demonstration (receptions, production, expedition) pour une entreprise."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Identifiant d'un administrateur de l'entreprise")

    def handle(self, *args, admin, **options):
        user = User.objects.filter(username=admin, role=User.Role.ADMIN).first()
        if user is None or user.tenant_id is None:
            raise CommandError(f"Aucun administrateur « {admin} ».")
        t = user.tenant_id
        with tenant_context(t):
            if Article.objects.filter(code="DEMO-FAR").exists():
                raise CommandError("Les données de démonstration existent déjà pour cette entreprise.")
            absent = {c: "absent" for c in allergen_codes()}
            flour = catalog.create_article(
                tenant_id=t, user=user, code="DEMO-FAR", name="Farine de blé (démo)", article_type="matiere",
                base_unit="kg", storage="ambiant", allergens=dict(absent, gluten="contient"),
            )
            catalog.create_conversion(tenant_id=t, user=user, article=flour, unit_name="sac", factor=Decimal("25"))
            butter = catalog.create_article(
                tenant_id=t, user=user, code="DEMO-BEU", name="Beurre (démo)", article_type="matiere",
                base_unit="kg", storage="refrigere", allergens=dict(absent, lait="contient"),
            )
            biscuit = catalog.create_article(
                tenant_id=t, user=user, code="DEMO-BIS", name="Biscuit sablé 200 g (démo)", article_type="fini",
                base_unit="unite", shelf_life_days=120,
            )
            mill = catalog.create_partner(
                tenant_id=t, user=user, name="DEMO Moulins", is_supplier=True, address="Zone portuaire, Abidjan"
            )
            dairy = catalog.create_partner(
                tenant_id=t, user=user, name="DEMO Laiterie", is_supplier=True, address="Yopougon, Abidjan"
            )
            shop = catalog.create_partner(
                tenant_id=t, user=user, name="DEMO Supermarché", is_customer=True, address="Plateau, Abidjan",
                phone="0102030405",
            )
            later = datetime.date.today() + datetime.timedelta(days=180)
            f1 = services.receive_lot(
                tenant_id=t, user=user, article=flour, supplier=mill, supplier_lot_code="DEMO-MOULIN-001",
                quantity=Decimal("20"), unit="sac", date_type="ddm", expiry_date=later,
            )
            b1 = services.receive_lot(
                tenant_id=t, user=user, article=butter, supplier=dairy, supplier_lot_code="DEMO-LAIT-042",
                quantity=Decimal("40"), unit="kg", date_type="dlc", expiry_date=later, temperature_c=Decimal("3.5"),
            )
            p1 = services.create_lot(
                tenant_id=t, user=user, article=biscuit, quantity=Decimal("1200"), entry_type="production",
                date_type="dlc", expiry_date=datetime.date.today() + datetime.timedelta(days=120),
            )
            p2 = services.create_lot(
                tenant_id=t, user=user, article=biscuit, quantity=Decimal("800"), entry_type="production",
                date_type="dlc", expiry_date=datetime.date.today() + datetime.timedelta(days=121),
            )
            for parent, child, qty in ((f1, p1, "150"), (b1, p1, "30"), (f1, p2, "100")):
                services.record_exit(tenant_id=t, user=user, lot_id=parent.id, movement_type="consommation",
                                     quantity=Decimal(qty))
                services.link_lots(tenant_id=t, user=user, parent=parent, child=child)
            services.record_exit(tenant_id=t, user=user, lot_id=p1.id, movement_type="expedition",
                                 quantity=Decimal("500"), partner=shop)
        self.stdout.write(self.style.SUCCESS(
            "Démonstration créée. Cherche « DEMO-MOULIN-001 » en aval, ou le lot "
            f"{p1.code} en amont, sur http://localhost:3000/tracabilite"
        ))
