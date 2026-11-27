"""Demonstration « mangue sechee bio » pour un exportateur de fruits seches (pilote).

Cree une ENTREPRISE DE DEMONSTRATION a part, avec ses propres comptes : les donnees existantes ne sont
jamais touchees. Producteurs, parcelles, quantites et dates sont fictifs.

Ce que le produit ne sait pas encore faire, et comment la demo le contourne :
- pas de champ « parcelle » : le code de parcelle est saisi dans le n° de lot fournisseur ;
- pas de statut bio par lot ni par producteur : le statut est porte par le nom de l'article ;
- pas d'ordre de fabrication (US-06 a US-08) : le sechage et l'ensachage sont enregistres par les
  briques create_lot, record_exit et link_lots, comme le fera la declaration de production.
"""

import datetime
import getpass
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalog import services as catalog
from catalog.selectors import allergen_codes
from core.management.checks import ensure_database_migrated
from core.tenancy import tenant_context
from lots import services
from lots.models import ApprovalRequest
from tenants import services as tenants
from tenants.models import Tenant, User
from tenants.selectors import find_user_by_username, username_taken

TENANT_NAME = "Vergers Bio du Nord (démo)"
# (identifiant, role, prenom, nom, poste)
ACCOUNTS = [
    ("demo.direction", User.Role.ADMIN, "Awa", "Bamba", "directeur"),
    ("demo.qualite", User.Role.QUALITE, "Mariam", "Koné", "responsable_qualite"),
    ("demo.production", User.Role.PRODUCTION, "Yao", "Kouassi", "responsable_production"),
    ("demo.reception", User.Role.OPERATEUR, "Issa", "Ouattara", "receptionnaire"),
]
# Producteurs fictifs : (nom, village, parcelle, surface en ha)
PRODUCERS = {
    "NAP-07": ("Coulibaly Souleymane (producteur démo)", "Napiéolédougou", "3,2"),
    "SIN-03": ("Soro Kalidou (producteur démo)", "Sinématiali", "4,5"),
    "KAR-12": ("Yéo Mariam (productrice démo)", "Karakoro", "2,8"),
    "NIO-05": ("Silué Brahima (producteur démo)", "Niofoin", "1,9"),
    "BON-21": ("Kouamé Ahou (productrice démo)", "Bonoua", "6,0"),
    "ADI-02": ("Aka Jean-Marc (producteur démo)", "Adiaké", "3,5"),
}


def _at(day, hour=9):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, 0)))


class Command(BaseCommand):
    help = "Cree une entreprise de demonstration « mangue sechee bio » avec ses comptes et son historique."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", help="Mot de passe commun aux 4 comptes de demo. Sinon demande au clavier."
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="Archive l'entreprise de demo existante (rien n'est efface) et en recree une neuve.",
        )

    def handle(self, *args, password=None, reset=False, **options):
        ensure_database_migrated()
        old_demo = self._existing_demo() if reset else None
        taken = [u for u, *_ in ACCOUNTS if username_taken(u)]
        if taken and old_demo is None:
            raise CommandError(
                "La démonstration est déjà chargée (identifiant " + taken[0] + " pris). Rien n'a été modifié. "
                "Pour repartir à neuf : ajoute --reset."
            )
        if not password:
            password = getpass.getpass("Mot de passe des comptes de démonstration (10 caractères minimum) : ")
            if password != getpass.getpass("Confirmer : "):
                raise CommandError("Les deux mots de passe sont différents.")
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        # Tout ou rien : une erreur au milieu n'en laisse aucune trace.
        with transaction.atomic():
            if old_demo is not None:
                tenants.archive_tenant(tenant_id=old_demo.id)
                self.stdout.write(f"Ancienne démonstration archivée : « {old_demo.name} ».")
            tenant, admin = tenants.create_tenant_with_admin(
                tenant_name=TENANT_NAME, username=ACCOUNTS[0][0], password=password
            )
            with tenant_context(tenant.id):
                summary = Demo(tenant.id, admin, password).build()

        self.stdout.write(self.style.SUCCESS(f"Entreprise « {TENANT_NAME} » créée."))
        self.stdout.write("Comptes (même mot de passe) : " + ", ".join(u for u, *_ in ACCOUNTS))
        for line in summary:
            self.stdout.write(line)

    def _existing_demo(self):
        """L'entreprise de demo a remettre a zero. Garde-fou : jamais une entreprise cliente.

        Elle doit porter le nom de la demo ET posseder les 4 comptes demo.*, et rien d'autre ne doit les porter.
        """
        users = [find_user_by_username(u) for u, *_ in ACCOUNTS]
        found = [u for u in users if u is not None]
        if not found:
            return None
        tenant_ids = {u.tenant_id for u in found}
        tenant = Tenant.objects.filter(pk__in=tenant_ids - {None}).first() if len(tenant_ids) == 1 else None
        if tenant is None or tenant.name != TENANT_NAME:
            raise CommandError(
                "Les comptes demo.* n'appartiennent pas tous à l'entreprise « " + TENANT_NAME + " ». "
                "Remise à zéro refusée, rien n'a été modifié."
            )
        return tenant


class Demo:
    def __init__(self, tenant_id, admin, password):
        self.t, self.admin, self.password = tenant_id, admin, password
        self.users = {}

    # Comptes ---------------------------------------------------------------

    def _accounts(self):
        username, _, first, last, job = ACCOUNTS[0]
        tenants.update_user(tenant_id=self.t, user=self.admin, target=self.admin, first_name=first, last_name=last,
                            job_title=job)
        self.users["admin"] = self.admin
        for username, role, first, last, job in ACCOUNTS[1:]:
            self.users[role] = tenants.create_user(
                tenant_id=self.t, user=self.admin, username=username, password=self.password, role=role,
                first_name=first, last_name=last, job_title=job, manager=self.admin,
            )

    # Referentiels ------------------------------------------------------------

    def _catalog(self):
        t, u = self.t, self.admin
        absent = {c: "absent" for c in allergen_codes()}
        a = {}
        a["mangue"] = catalog.create_article(
            tenant_id=t, user=u, code="MGAF", name="Mangue Amélie fraîche, bio UE", article_type="matiere",
            base_unit="kg", storage="ambiant", allergens=absent,
        )
        catalog.create_conversion(tenant_id=t, user=u, article=a["mangue"], unit_name="caisse", factor=Decimal("20"))
        a["ananas"] = catalog.create_article(
            tenant_id=t, user=u, code="ANAF", name="Ananas Pain de sucre frais, bio UE", article_type="matiere",
            base_unit="kg", storage="ambiant", allergens=absent,
        )
        catalog.create_conversion(tenant_id=t, user=u, article=a["ananas"], unit_name="caisse", factor=Decimal("15"))
        a["mangue_sechee"] = catalog.create_article(
            tenant_id=t, user=u, code="MGAS", name="Mangue Amélie séchée en vrac, bio UE", article_type="semi_fini",
            base_unit="kg", storage="ambiant", shelf_life_days=365, allergens=absent,
        )
        a["ananas_seche"] = catalog.create_article(
            tenant_id=t, user=u, code="ANAS", name="Ananas séché en vrac, bio UE", article_type="semi_fini",
            base_unit="kg", storage="ambiant", shelf_life_days=365, allergens=absent,
        )
        a["sachet_vide"] = catalog.create_article(
            tenant_id=t, user=u, code="SACK", name="Sachet kraft refermable 100 g", article_type="emballage",
            base_unit="unite",
        )
        catalog.create_conversion(tenant_id=t, user=u, article=a["sachet_vide"], unit_name="carton",
                                  factor=Decimal("500"))
        a["sachet"] = catalog.create_article(
            tenant_id=t, user=u, code="MGS100", name="Mangue séchée bio, sachet 100 g", article_type="fini",
            base_unit="unite", storage="ambiant", shelf_life_days=365, allergens=absent,
        )
        catalog.create_conversion(tenant_id=t, user=u, article=a["sachet"], unit_name="carton", factor=Decimal("50"))

        p = {}
        for parcel, (name, village, area) in PRODUCERS.items():
            p[parcel] = catalog.create_partner(
                tenant_id=t, user=u, name=name, is_supplier=True, city=village,
                address=f"Parcelle {parcel} ({area} ha), {village}. Certifié bio UE, groupe de producteurs.",
            )
        p["emballages"] = catalog.create_partner(
            tenant_id=t, user=u, name="Emballages Lagunaires (démo)", is_supplier=True, city="Abidjan",
            address="Zone industrielle de Yopougon, Abidjan",
        )
        p["rotterdam"] = catalog.create_partner(
            tenant_id=t, user=u, name="Importateur bio Rotterdam (démo)", is_customer=True, city="Rotterdam",
            address="Port de Rotterdam, Pays-Bas",
        )
        p["lyon"] = catalog.create_partner(
            tenant_id=t, user=u, name="Grossiste bio Lyon (démo)", is_customer=True, city="Lyon",
            address="Marché d'intérêt national, Corbas, France",
        )
        return a, p

    # Historique --------------------------------------------------------------

    def _receive(self, article, partner, parcel, caisses, day, visual_ok=True, reason_code=""):
        return services.receive_lot(
            tenant_id=self.t, user=self.users[User.Role.OPERATEUR], article=article, supplier=partner,
            supplier_lot_code=parcel, quantity=Decimal(caisses), unit="caisse", date_type="ddm",
            # Fruit frais : date courte, simple repere de fraicheur.
            expiry_date=day + datetime.timedelta(days=10), visual_ok=visual_ok, reason_code=reason_code,
            occurred_at=_at(day, 8),
        )

    def _transform(self, *, inputs, article, quantity, day, expiry):
        """Sechage ou ensachage : consomme les lots d'entree et cree le lot produit, relie a ses parents."""
        prod = self.users[User.Role.PRODUCTION]
        child = services.create_lot(
            tenant_id=self.t, user=prod, article=article, quantity=Decimal(quantity), entry_type="production",
            date_type="ddm", expiry_date=expiry, occurred_at=_at(day, 16),
        )
        for parent, qty in inputs:
            services.record_exit(tenant_id=self.t, user=prod, lot_id=parent.id, movement_type="consommation",
                                 quantity=Decimal(qty), occurred_at=_at(day, 10))
            services.link_lots(tenant_id=self.t, user=prod, parent=parent, child=child)
        return child

    def build(self):
        self._accounts()
        a, p = self._catalog()
        q, prod = self.users[User.Role.QUALITE], self.users[User.Role.PRODUCTION]
        d = datetime.date

        # Saison mangue 2026. Rendement fictif : environ 10 kg de mangue fraiche pour 1 kg sechee.
        r1 = self._receive(a["mangue"], p["NAP-07"], "NAP-07", "60", d(2026, 6, 9))
        r2 = self._receive(a["mangue"], p["SIN-03"], "SIN-03", "80", d(2026, 6, 9))
        r3 = self._receive(a["mangue"], p["KAR-12"], "KAR-12", "50", d(2026, 6, 9))
        # Livraison refusee (mouche des fruits), detruite apres double validation.
        bad = self._receive(a["mangue"], p["NIO-05"], "NIO-05", "40", d(2026, 6, 9), visual_ok=False,
                            reason_code="contamination")
        req = services.request_approval(tenant_id=self.t, user=q, lot_id=bad.id, action="destroy",
                                        reason_code="contamination")
        services.approve_request(tenant_id=self.t, user=prod, request_id=req.id)

        ddm = d(2027, 6, 10)
        sec1 = self._transform(inputs=[(r1, "1200"), (r2, "1600"), (r3, "1000")], article=a["mangue_sechee"],
                               quantity="380", day=d(2026, 6, 10), expiry=ddm)
        # Dans l'ordre chronologique : la liste des receptions suit l'ordre de saisie.
        sachets = services.receive_lot(
            tenant_id=self.t, user=self.users[User.Role.OPERATEUR], article=a["sachet_vide"],
            supplier=p["emballages"], supplier_lot_code="EL-2606-114", quantity=Decimal("12"), unit="carton",
            occurred_at=_at(d(2026, 6, 15), 8),
        )
        r4 = self._receive(a["mangue"], p["KAR-12"], "KAR-12", "45", d(2026, 6, 16))
        r5 = self._receive(a["mangue"], p["SIN-03"], "SIN-03", "55", d(2026, 6, 16))
        sec2 = self._transform(inputs=[(r4, "900"), (r5, "1100")], article=a["mangue_sechee"], quantity="200",
                               day=d(2026, 6, 17), expiry=d(2027, 6, 17))

        s1 = self._transform(inputs=[(sec1, "350"), (sachets, "3500")], article=a["sachet"], quantity="3500",
                             day=d(2026, 6, 20), expiry=ddm)
        s2 = self._transform(inputs=[(sec2, "190"), (sachets, "1900")], article=a["sachet"], quantity="1900",
                             day=d(2026, 6, 24), expiry=d(2027, 6, 17))
        services.record_exit(tenant_id=self.t, user=prod, lot_id=s1.id, movement_type="expedition",
                             quantity=Decimal("3000"), partner=p["rotterdam"], occurred_at=_at(d(2026, 7, 6), 7))
        services.record_exit(tenant_id=self.t, user=prod, lot_id=s2.id, movement_type="expedition",
                             quantity=Decimal("1500"), partner=p["lyon"], occurred_at=_at(d(2026, 7, 9), 7))

        # Saison ananas (en cours). Le lot seche attend l'analyse de residus : debloque en direct pendant la demo.
        today = timezone.localdate()
        day_in = today - datetime.timedelta(days=3)
        r6 = self._receive(a["ananas"], p["BON-21"], "BON-21", "160", day_in)
        dry = self._transform(inputs=[(r6, "2400")], article=a["ananas_seche"], quantity="160",
                              day=day_in + datetime.timedelta(days=1), expiry=day_in + datetime.timedelta(days=366))
        services.block_lot(tenant_id=self.t, user=q, lot_id=dry.id, reason_code="autre",
                           comment="En attente du résultat d'analyse de résidus de pesticides")

        assert ApprovalRequest.objects.filter(status=ApprovalRequest.Status.APPROVED).count() == 1
        return [
            f"Amont (de quoi est fait ce sachet ?) : cherche {s1.code}",
            "Aval (rappel d'une parcelle) : cherche NAP-07",
            f"Lot bloqué à débloquer en direct : {dry.code}",
            f"Lot détruit après double validation : {bad.code}",
        ]
