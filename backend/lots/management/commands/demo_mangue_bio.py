"""Demonstration « mangue sechee bio » pour un exportateur de fruits seches (pilote).

Cree une ENTREPRISE DE DEMONSTRATION a part, avec ses propres comptes : les donnees existantes ne sont
jamais touchees. Producteurs, parcelles, sites, equipements, quantites, conteneur et certificat sont fictifs.

--reset : archive l'entreprise de demo existante (renommee, desactivee, comptes bloques, rien d'efface)
puis en recree une neuve. Le journal reste en insertion seule.

Parcours montre : parcelles bio et en conversion, reception, murissement, un lot reparti sur deux
sechoirs, cartons de vrac de 10 kg, palette, controle qualite, conteneur avec certificat d'inspection,
bilan matiere avec un ecart signale, rappel depuis un carton.
Rendement de sechage : 13 kg de mangue fraiche pour 1 kg sechee (Kent, Amelie), jusqu'a 18 pour 1
(Brooks tardive), source publique COLEAD, etude sur la mangue transformee, 2023. Fourchette de l'article :
5,5 a 7,7 %. L'historique est date de la saison passee : il est saisi « apres coup » (motif ressaisie).
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
from lots.reasons import QUALITY_CRITERIA
from production import services as production
from shipping import services as shipping
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
# Producteurs fictifs : parcelle -> (nom, village, surface en ha, statut bio)
PRODUCERS = {
    "NAP-07": ("Coulibaly Souleymane (producteur démo)", "Napiéolédougou", "3.2", "bio"),
    "SIN-03": ("Soro Kalidou (producteur démo)", "Sinématiali", "4.5", "bio"),
    "KAR-12": ("Yéo Mariam (productrice démo)", "Karakoro", "2.8", "bio"),
    "NIO-05": ("Silué Brahima (producteur démo)", "Niofoin", "1.9", "bio"),
    "BON-21": ("Kouamé Ahou (productrice démo)", "Bonoua", "6.0", "bio"),
    "ADI-02": ("Aka Jean-Marc (producteur démo)", "Adiaké", "3.5", "conversion"),
    "JAC-04": ("N'Guessan Koffi (producteur démo)", "Jacqueville", "5.0", "bio"),
}
# Etapes de l'entreprise, dans l'ordre du procede fruits seches (mangue, ananas, coco). « Préparation » reste
# desactivee : l'entreprise declare lavage, epluchage et decoupe separement.
STEP_ORDER = [
    "murissement", "lavage", "tri", "epluchage_decoupe", "pretraitement", "cassage", "parage", "rapage",
    "pasteurisation", "sechage", "refroidissement", "tri_finition", "conditionnement", "palettisation",
]
# Parcours par produit : nom -> (etapes, articles)
ROUTES = {
    "Mangue séchée": (
        ["murissement", "lavage", "tri", "epluchage_decoupe", "pretraitement", "sechage", "tri_finition",
         "conditionnement", "palettisation"],
        ["mangue", "mure", "sechee", "carton", "palette"],
    ),
    "Ananas séché": (
        ["lavage", "epluchage_decoupe", "sechage", "tri_finition", "conditionnement", "palettisation"],
        ["ananas", "ananas_epluche", "ananas_seche", "ananas_carton"],
    ),
    "Coco râpée séchée": (
        ["cassage", "parage", "lavage", "rapage", "pasteurisation", "sechage", "refroidissement",
         "conditionnement", "palettisation"],
        ["coco", "coco_amande", "coco_paree", "coco_rapee", "coco_sechee", "coco_carton"],
    ),
}
# Historique de la saison passee : saisi apres coup, avec son motif.
LATE = {"late_reason_code": "ressaisie_papier"}


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
        self.parcels = {}

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

        def article(key, code, name, kind, unit="kg", conversion=None, **extra):
            if kind == "matiere":
                extra["allergens"] = absent
            a[key] = catalog.create_article(tenant_id=t, user=u, code=code, name=name, article_type=kind,
                                            base_unit=unit, storage="" if kind == "emballage" else "ambiant", **extra)
            if conversion:
                catalog.create_conversion(tenant_id=t, user=u, article=a[key], unit_name=conversion[0],
                                          factor=Decimal(conversion[1]))

        article("mangue", "MGAF", "Mangue Amélie fraîche", "matiere", conversion=("caisse", "20"))
        # Rendement de reference du murissement : VALEUR FICTIVE de demonstration (95 a 100 %), a remplacer par
        # celle du pilote dans les referentiels.
        article("mure", "MGAM", "Mangue Amélie mûre", "matiere", yield_min_pct=Decimal("95"), yield_max_pct=Decimal("100"))
        # Fourchette COLEAD 2023 : 13:1 (7,7 %) a 18:1 (5,6 %).
        article("sechee", "MGAS", "Mangue Amélie séchée en vrac", "semi_fini", shelf_life_days=365,
                yield_min_pct=Decimal("5.5"), yield_max_pct=Decimal("7.7"))
        article("carton", "MGAC", "Mangue séchée, carton vrac 10 kg", "fini", conversion=("carton", "10"),
                shelf_life_days=365)
        article("palette", "MGAP", "Mangue séchée, palette de cartons", "fini", shelf_life_days=365)
        article("ananas", "ANAF", "Ananas Pain de sucre frais", "matiere", conversion=("caisse", "15"))
        # Ananas et coco : pas de fourchette de rendement (aucune valeur publique verifiee, a fournir par le pilote).
        # Les quantites de l'historique ananas et coco sont FICTIVES.
        article("ananas_epluche", "ANAP", "Ananas épluché tranché", "semi_fini", shelf_life_days=2)
        article("ananas_seche", "ANAS", "Ananas séché en vrac", "semi_fini", shelf_life_days=365)
        article("ananas_carton", "ANAC", "Ananas séché, carton vrac 10 kg", "fini", conversion=("carton", "10"),
                shelf_life_days=365)
        article("coco", "COCF", "Noix de coco décortiquée", "matiere", conversion=("sac", "50"))
        article("coco_amande", "COCA", "Amande de coco écalée", "semi_fini", shelf_life_days=2)
        article("coco_paree", "COCB", "Amande de coco parée", "semi_fini", shelf_life_days=2)
        article("coco_rapee", "COCR", "Coco râpée humide", "semi_fini", shelf_life_days=1)
        article("coco_sechee", "COCS", "Coco râpée séchée en vrac", "semi_fini", shelf_life_days=365)
        article("coco_carton", "COCK", "Coco râpée séchée, carton 10 kg", "fini", conversion=("carton", "10"),
                shelf_life_days=365)
        article("carton_vide", "CTV10", "Carton kraft vide 10 kg avec sac intérieur", "emballage", unit="unite",
                conversion=("paquet", "50"))

        p = {}
        for parcel, (name, village, area, status) in PRODUCERS.items():
            p[parcel] = catalog.create_partner(
                tenant_id=t, user=u, name=name, is_supplier=True, city=village,
                address=f"{village}. Membre du groupe de producteurs de démonstration.",
            )
            self.parcels[parcel] = catalog.create_parcel(
                tenant_id=t, user=u, producer=p[parcel], code=parcel, locality=village, area_ha=Decimal(area),
                organic_status=status,
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
        p["hambourg"] = catalog.create_partner(
            tenant_id=t, user=u, name="Biscuiterie bio Hambourg (démo)", is_customer=True, city="Hambourg",
            address="Port de Hambourg, Allemagne",
        )
        return a, p

    def _steps_and_routes(self, a):
        t, u = self.t, self.admin
        production.configure_steps(tenant_id=t, user=u, steps=[{"code": c, "is_active": True} for c in STEP_ORDER])
        for name, (steps, articles) in ROUTES.items():
            production.create_route(tenant_id=t, user=u, name=name, steps=steps, articles=[a[k] for k in articles])

    def _sites(self):
        t, u = self.t, self.admin
        nord = tenants.create_site(tenant_id=t, user=u, name="Usine Nord (démo)", address="Site fictif")
        sud = tenants.create_site(tenant_id=t, user=u, name="Usine Sud (démo)", address="Site fictif")
        e = {}
        for code, name, kind, site in [
            ("MUR-N1", "Aire de mûrissement Nord", "murissement", nord),
            ("SEC-N1", "Séchoir Nord 1", "sechoir", nord),
            ("SEC-N2", "Séchoir Nord 2", "sechoir", nord),
            ("SEC-N3", "Séchoir Nord 3", "sechoir", nord),
            ("CDT-N1", "Ligne de conditionnement Nord", "conditionnement", nord),
            ("SEC-S1", "Séchoir Sud 1", "sechoir", sud),
            ("PRE-S1", "Table d'épluchage Sud", "preparation", sud),
            ("CAS-S1", "Poste de cassage coco Sud", "preparation", sud),
            ("RAP-S1", "Râpeuse coco Sud", "preparation", sud),
            ("PAS-S1", "Pasteurisateur Sud", "autre", sud),
            ("SEC-S2", "Séchoir Sud 2 (coco)", "sechoir", sud),
            ("REF-S1", "Table de refroidissement Sud", "autre", sud),
            ("CDT-S1", "Ligne de conditionnement Sud", "conditionnement", sud),
        ]:
            e[code] = production.create_equipment(tenant_id=t, user=u, code=code, name=name, equipment_type=kind,
                                                  site=site)
        return {"nord": nord, "sud": sud}, e

    # Historique --------------------------------------------------------------

    def _receive(self, article, parcel, caisses, day, site, visual_ok=True, reason_code="", unit="caisse"):
        parcel = self.parcels[parcel]
        return services.receive_lot(
            tenant_id=self.t, user=self.users[User.Role.OPERATEUR], article=article, supplier=parcel.producer,
            supplier_lot_code="", parcel=parcel, quantity=Decimal(caisses), unit=unit, date_type="ddm",
            # Fruit frais : date courte, simple repere de fraicheur.
            expiry_date=day + datetime.timedelta(days=10), visual_ok=visual_ok, reason_code=reason_code,
            occurred_at=_at(day, 8), site=site, **LATE,
        )

    def _run(self, step, equipment, inputs, article, quantity, start, end, unit=None, waste=None, user=None):
        """Declaration d'etape, saisie apres coup (historique de la saison passee)."""
        return production.declare_run(
            tenant_id=self.t, user=user or self.users[User.Role.PRODUCTION], step=step, equipment=equipment,
            inputs=[(lot, Decimal(q)) for lot, q in inputs], output_article=article, output_quantity=Decimal(quantity),
            output_unit=unit, started_at=start, ended_at=end,
            waste_quantity=Decimal(waste[0]) if waste else None, waste_code=waste[1] if waste else "",
            waste_comment=waste[2] if waste and len(waste) > 2 else "", **LATE,
        ).output_lot

    def _qc(self, lot, day, hour, moisture, failed=(), comment=""):
        return services.record_quality_check(
            tenant_id=self.t, user=self.users[User.Role.QUALITE], lot_id=lot.id, moisture_pct=Decimal(moisture),
            checks={code: "nok" if code in failed else "ok" for code in QUALITY_CRITERIA}, comment=comment,
            checked_at=_at(day, hour), **LATE,
        )

    def build(self):
        self._accounts()
        a, p = self._catalog()
        self._steps_and_routes(a)
        sites, e = self._sites()
        nord, sud = sites["nord"], sites["sud"]
        q, prod = self.users[User.Role.QUALITE], self.users[User.Role.PRODUCTION]
        d = datetime.date

        # Saison mangue 2026, usine Nord. Trois parcelles bio livrent le meme jour.
        r1 = self._receive(a["mangue"], "NAP-07", "60", d(2026, 6, 9), nord)
        r2 = self._receive(a["mangue"], "SIN-03", "80", d(2026, 6, 9), nord)
        r3 = self._receive(a["mangue"], "KAR-12", "50", d(2026, 6, 9), nord)
        # Livraison refusee (mouche des fruits), detruite apres double validation.
        bad = self._receive(a["mangue"], "NIO-05", "40", d(2026, 6, 9), nord, visual_ok=False,
                            reason_code="contamination")
        req = services.request_approval(tenant_id=self.t, user=q, lot_id=bad.id, action="destroy",
                                        reason_code="contamination")
        services.approve_request(tenant_id=self.t, user=prod, request_id=req.id)
        cartons_vides = services.receive_lot(
            tenant_id=self.t, user=self.users[User.Role.OPERATEUR], article=a["carton_vide"],
            supplier=p["emballages"], supplier_lot_code="EL-2606-114", quantity=Decimal("2"), unit="paquet",
            occurred_at=_at(d(2026, 6, 9), 10), site=nord, **LATE,
        )

        # Murissement (rendement de reference fictif, a remplacer par celui du pilote), puis le lot mur est reparti
        # sur deux sechoirs. Le sechoir 2 sort sous la fourchette : ecart signale au bilan.
        mure = self._run("murissement", e["MUR-N1"], [(r1, "1200"), (r2, "1600"), (r3, "1000")], a["mure"],
                         "3724", _at(d(2026, 6, 9), 14), _at(d(2026, 6, 12), 7))
        sec1 = self._run("sechage", e["SEC-N1"], [(mure, "1900")], a["sechee"], "146",
                         _at(d(2026, 6, 12), 8), _at(d(2026, 6, 13), 6), waste=("570", "peaux_noyaux"))
        sec2 = self._run("sechage", e["SEC-N2"], [(mure, "1824")], a["sechee"], "99",
                         _at(d(2026, 6, 12), 9), _at(d(2026, 6, 13), 7), waste=("547", "peaux_noyaux"))
        c1 = self._run("conditionnement", e["CDT-N1"], [(sec1, "146"), (cartons_vides, "14")], a["carton"], "14",
                       _at(d(2026, 6, 15), 8), _at(d(2026, 6, 15), 11), unit="carton", waste=("6", "chutes"))
        c2 = self._run("conditionnement", e["CDT-N1"], [(sec2, "99"), (cartons_vides, "9")], a["carton"], "9",
                       _at(d(2026, 6, 15), 13), _at(d(2026, 6, 15), 15), unit="carton", waste=("9", "chutes"))
        self._qc(c1, d(2026, 6, 15), 12, "16.5")
        self._qc(c2, d(2026, 6, 15), 16, "17.0")
        pal = self._run("palettisation", e["CDT-N1"], [(c1, "140"), (c2, "90")], a["palette"], "230",
                        _at(d(2026, 6, 16), 9), _at(d(2026, 6, 16), 10))
        shipping.create_shipment(
            tenant_id=self.t, user=prod, customer=p["rotterdam"], lines=[(pal, Decimal("230"), None)],
            shipped_at=_at(d(2026, 7, 6), 7), container_number="TRCU2606003", seal_number="SCELLE-DEMO-0001",
            export_document_ref="COI.CI.2026.DEMO-0001", bill_of_lading="BL-DEMO-0001", site=nord, **LATE,
        )

        # Deuxieme lot de la saison : autres livraisons, autre sechoir, en partie expedie a Lyon.
        r4 = self._receive(a["mangue"], "KAR-12", "45", d(2026, 6, 16), nord)
        r5 = self._receive(a["mangue"], "SIN-03", "55", d(2026, 6, 16), nord)
        # Erreur de saisie corrigee : une premiere declaration avec une mauvaise quantite, annulee avec motif.
        # Les mangues reviennent en stock, le lot produit par erreur est bloque, puis la bonne declaration suit.
        erreur = self._run("murissement", e["MUR-N1"], [(r4, "900"), (r5, "1100")], a["mure"], "1690",
                           _at(d(2026, 6, 16), 14), _at(d(2026, 6, 19), 7))
        production.cancel_run(tenant_id=self.t, user=prod, run_id=erreur.production_run.id,
                              reason_code="mauvaise_quantite")
        mure2 = self._run("murissement", e["MUR-N1"], [(r4, "900"), (r5, "1100")], a["mure"], "1960",
                          _at(d(2026, 6, 16), 14), _at(d(2026, 6, 19), 7))
        sec3 = self._run("sechage", e["SEC-N3"], [(mure2, "1960")], a["sechee"], "150",
                         _at(d(2026, 6, 19), 8), _at(d(2026, 6, 20), 6), waste=("590", "peaux_noyaux"))
        c3 = self._run("conditionnement", e["CDT-N1"], [(sec3, "150"), (cartons_vides, "15")], a["carton"], "15",
                       _at(d(2026, 6, 22), 8), _at(d(2026, 6, 22), 11), unit="carton")
        self._qc(c3, d(2026, 6, 22), 12, "16.8")
        shipping.create_shipment(
            tenant_id=self.t, user=prod, customer=p["lyon"], lines=[(c3, Decimal("8"), "carton")],
            shipped_at=_at(d(2026, 7, 9), 7), container_number="TRCU2607000", seal_number="SCELLE-DEMO-0002",
            export_document_ref="COI.CI.2026.DEMO-0002", site=nord, **LATE,
        )

        # Saison ananas (en cours), usine Sud. Lot bio epluche puis seche, le reste attend en stock. Le lot seche
        # attend l'analyse de residus : debloque en direct. Un lot « en conversion » sert a montrer le refus
        # de melange.
        today = timezone.localdate()
        day_in = today - datetime.timedelta(days=3)
        r6 = self._receive(a["ananas"], "BON-21", "200", day_in, sud)
        conv = self._receive(a["ananas"], "ADI-02", "40", day_in, sud)
        peeled = self._run("epluchage_decoupe", e["PRE-S1"], [(r6, "2400")], a["ananas_epluche"], "1320",
                           _at(day_in, 10), _at(day_in, 13), waste=("1080", "peaux_noyaux"))
        dry = self._run("sechage", e["SEC-S1"], [(peeled, "1320")], a["ananas_seche"], "200",
                        _at(day_in, 14), _at(day_in + datetime.timedelta(days=1), 6))
        # Cartons vides envoyes de l'usine Nord vers l'usine Sud pour l'ananas : transfert d'une partie du lot.
        services.transfer_lot(tenant_id=self.t, user=prod, lot_id=cartons_vides.id, to_site=sud,
                              quantity=Decimal("30"), occurred_at=_at(day_in, 9), **LATE)
        services.block_lot(tenant_id=self.t, user=q, lot_id=dry.id, reason_code="autre",
                           comment="En attente du résultat d'analyse de résidus de pesticides")

        # Coco rapee sechee, octobre 2026, usine Sud : toutes les etapes propres a la coco. Quantites fictives.
        oct_ = d(2026, 10, 6)
        coco = self._receive(a["coco"], "JAC-04", "60", oct_, sud, unit="sac")
        cartons_sud = services.receive_lot(
            tenant_id=self.t, user=self.users[User.Role.OPERATEUR], article=a["carton_vide"],
            supplier=p["emballages"], supplier_lot_code="EL-2610-031", quantity=Decimal("2"), unit="paquet",
            occurred_at=_at(oct_, 10), site=sud, **LATE,
        )
        amande = self._run("cassage", e["CAS-S1"], [(coco, "3000")], a["coco_amande"], "1350",
                           _at(oct_, 9), _at(oct_, 12), waste=("1650", "autre", "Coques et eau de coco"))
        paree = self._run("parage", e["CAS-S1"], [(amande, "1350")], a["coco_paree"], "1150",
                          _at(oct_, 12), _at(oct_, 15), waste=("200", "autre", "Pellicule brune retirée au parage"))
        rapee = self._run("rapage", e["RAP-S1"], [(paree, "1150")], a["coco_rapee"], "1140",
                          _at(oct_, 15), _at(oct_, 16), waste=("10", "chutes"))
        pasteur = self._run("pasteurisation", e["PAS-S1"], [(rapee, "1140")], a["coco_rapee"], "1135",
                            _at(oct_, 16), _at(oct_, 17), waste=("5", "chutes"))
        seche = self._run("sechage", e["SEC-S2"], [(pasteur, "1135")], a["coco_sechee"], "585",
                          _at(oct_, 17), _at(d(2026, 10, 7), 5))
        froid = self._run("refroidissement", e["REF-S1"], [(seche, "585")], a["coco_sechee"], "582",
                          _at(d(2026, 10, 7), 6), _at(d(2026, 10, 7), 8), waste=("3", "chutes"))
        k1 = self._run("conditionnement", e["CDT-S1"], [(froid, "300"), (cartons_sud, "30")], a["coco_carton"],
                       "30", _at(d(2026, 10, 7), 9), _at(d(2026, 10, 7), 11), unit="carton")
        k2 = self._run("conditionnement", e["CDT-S1"], [(froid, "282"), (cartons_sud, "28")], a["coco_carton"],
                       "28", _at(d(2026, 10, 7), 13), _at(d(2026, 10, 7), 15), unit="carton", waste=("2", "chutes"))
        self._qc(k1, d(2026, 10, 7), 12, "3.0")
        # Second lot trop humide : controle non conforme, le lot est bloque automatiquement.
        self._qc(k2, d(2026, 10, 7), 16, "6.5", failed=("humidite",))
        shipping.create_shipment(
            tenant_id=self.t, user=prod, customer=p["hambourg"], lines=[(k1, Decimal("30"), "carton")],
            shipped_at=_at(d(2026, 10, 20), 7), container_number="TRCU2609002", seal_number="SCELLE-DEMO-0003",
            export_document_ref="COI.CI.2026.DEMO-0003", bill_of_lading="BL-DEMO-0003", site=sud, **LATE,
        )

        assert ApprovalRequest.objects.filter(status=ApprovalRequest.Status.APPROVED).count() == 1
        return [
            f"Rappel depuis un carton (séchoir 2, écart de rendement) : cherche {c2.code}",
            "Rappel depuis un conteneur : cherche TRCU2606003",
            f"Mélange refusé en direct : épluche ensemble {r6.code} (bio) et {conv.code} (en conversion)",
            f"Lot bloqué à débloquer en direct : {dry.code}",
            "Coco râpée, rappel depuis un conteneur : cherche TRCU2609002",
            f"Contrôle qualité non conforme (humidité), lot bloqué : {k2.code}",
            f"Lot détruit après double validation : {bad.code}",
        ]
