"""Demonstration « fruits seches bio » pour un exportateur (mangue, ananas, coco), entreprise de demo a part.

Cree une ENTREPRISE DE DEMONSTRATION a part, avec ses propres comptes : les donnees existantes ne sont
jamais touchees. Producteurs, parcelles, sites, equipements, clients, conteneurs et certificats sont FICTIFS.

--reset : archive l'entreprise de demo existante (renommee, desactivee, comptes bloques, rien d'efface)
puis en recree une neuve. Le journal reste en insertion seule.

Chiffres de reference (sources publiques, citees dans le script de demo) :
- Mangue : 13 kg fraiche pour 1 kg sechee (Amelie, Kent), jusqu'a 18 pour 1 en fin de saison (COLEAD, etude sur
  la mangue transformee, 2023). Sechoir a tunnel : environ 220 kg de mangue sechee par cycle de 16 a 24 h (COLEAD).
- Humidite maximale du produit sec : mangue 15 %, ananas 20 % (CBI, mangue et ananas seches), coco rapee 3 %
  (norme APCC de la coco dessechee).
- Eau du fruit frais : mangue 83,5 % (USDA FoodData Central 169910), ananas 86 % (USDA 169124), chair de coco 47 %
  (USDA 170169). Part comestible : mangue environ 63 %, ananas environ 43 % (rapport des tables McCance et
  Widdowson, CoFID 2021, chair seule et fruit entier).
- Les fourchettes de rendement du sechage viennent d'un bilan de matiere seche (eau du frais, humidite visee) :
  mangue 14 a 19 % de la pulpe, ananas 13 a 17 %, coco 50 a 55 %. Les rendements de murissement, de lavage, de tri,
  de cassage et de parage sont FICTIFS (a remplacer par ceux du pilote).

Horloge simulee : l'historique couvre une saison passee. Pour que chaque saisie porte une heure de saisie realiste
(quelques minutes apres le geste), la commande avance une horloge simulee pendant la creation, puis rend l'heure
reelle. Seules trois saisies sont volontairement tardives, avec leur motif. Rien n'est modifie apres coup :
le journal et les mouvements restent en insertion seule.
"""

import datetime
import getpass
from decimal import ROUND_DOWN, Decimal

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalog import services as catalog
from catalog.selectors import allergen_codes
from core.management.checks import ensure_database_migrated
from core.tenancy import tenant_context
from dashboard import services as dashboard
from lots import services
from lots.models import Movement
from lots.reasons import QUALITY_CRITERIA
from production import services as production
from shipping import services as shipping
from shipping.services import container_check_digit
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
    "TIO-02": ("Tuo Lassina (producteur démo)", "Tioroniaradougou", "3.6", "bio"),
    "NIO-05": ("Silué Brahima (producteur démo)", "Niofoin", "1.9", "bio"),
    "BON-21": ("Kouamé Ahou (productrice démo)", "Bonoua", "6.0", "bio"),
    "ALE-08": ("Ehui Clarisse (productrice démo)", "Alépé", "4.0", "bio"),
    "TIA-11": ("Konan Serge (producteur démo)", "Tiassalé", "5.5", "bio"),
    "ADI-02": ("Aka Jean-Marc (producteur démo)", "Adiaké", "3.5", "conversion"),
    "JAC-04": ("N'Guessan Koffi (producteur démo)", "Jacqueville", "5.0", "bio"),
    "GRB-06": ("Assi Marcelle (productrice démo)", "Grand-Bassam", "3.0", "bio"),
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
        ["mangue", "mure", "lavee", "pulpe", "sechee", "triee", "carton", "palette"],
    ),
    "Ananas séché": (
        ["lavage", "epluchage_decoupe", "sechage", "tri_finition", "conditionnement", "palettisation"],
        ["ananas", "ananas_lave", "ananas_epluche", "ananas_seche", "ananas_carton"],
    ),
    "Coco râpée séchée": (
        ["cassage", "parage", "lavage", "rapage", "pasteurisation", "sechage", "refroidissement",
         "conditionnement", "palettisation"],
        ["coco", "coco_amande", "coco_paree", "coco_rapee", "coco_sechee", "coco_froide", "coco_carton"],
    ),
}
H = datetime.timedelta(hours=1)
MIN = datetime.timedelta(minutes=1)
D = datetime.date

# Mangue, saison 2026, usine Nord. (jour de reception, livraisons (parcelle, caisses de 20 kg), attente du fruit mur
# avant l'epluchage en heures, sechoir, part de pulpe, rendement du sechage, humidite au controle).
# 143 caisses = 2 860 kg = un cycle de sechoir (environ 220 kg seches a 13 pour 1, COLEAD). Parts de pulpe et
# attentes FICTIVES. Fin de saison : rendement plus faible (COLEAD : jusqu'a 18 pour 1), signale « bas ».
MANGO_HISTORY = [
    (D(2026, 4, 13), [("NAP-07", 75), ("SIN-03", 68)], 56, "SEC-N1", "0.53", "0.150", "14.2"),
    (D(2026, 4, 20), [("KAR-12", 70), ("TIO-02", 73)], 62, "SEC-N3", "0.52", "0.152", "13.8"),
    (D(2026, 4, 27), [("NAP-07", 72), ("SIN-03", 71)], 58, "SEC-N1", "0.53", "0.148", "14.5"),
    (D(2026, 5, 4), [("KAR-12", 75), ("TIO-02", 68)], 70, "SEC-N3", "0.52", "0.150", "13.6"),
    (D(2026, 5, 11), [("NAP-07", 70), ("SIN-03", 73)], 74, "SEC-N1", "0.52", "0.151", "14.0"),
    (D(2026, 5, 18), [("KAR-12", 74), ("TIO-02", 69)], 66, "SEC-N2", "0.52", "0.149", "13.9"),
    (D(2026, 5, 25), [("NAP-07", 71), ("SIN-03", 72)], 80, "SEC-N3", "0.53", "0.150", "14.3"),
    (D(2026, 6, 1), [("KAR-12", 73), ("TIO-02", 70)], 72, "SEC-N1", "0.52", "0.150", "14.1"),
    (D(2026, 6, 23), [("NAP-07", 72), ("SIN-03", 71)], 60, "SEC-N1", "0.52", "0.148", "14.6"),
    (D(2026, 6, 30), [("KAR-12", 70), ("TIO-02", 73)], 64, "SEC-N3", "0.51", "0.149", "14.4"),
    (D(2026, 7, 7), [("NAP-07", 74), ("SIN-03", 69)], 56, "SEC-N2", "0.51", "0.147", "14.8"),
    (D(2026, 7, 14), [("KAR-12", 72), ("TIO-02", 71)], 62, "SEC-N1", "0.50", "0.145", "13.9"),
    (D(2026, 7, 21), [("NAP-07", 73), ("SIN-03", 70)], 52, "SEC-N3", "0.50", "0.142", "14.2"),
    (D(2026, 7, 28), [("KAR-12", 71), ("TIO-02", 72)], 48, "SEC-N1", "0.48", "0.130", "14.7"),
]
# Saison 2025, meme usine : sert a comparer saison contre saison au tableau de bord. FICTIVE (rendements un peu
# plus faibles qu'en 2026, attente plus longue avant l'epluchage : un seul epluchage par jour cette annee-la).
MANGO_2025 = [
    (D(2025, 4, 14), [("NAP-07", 70), ("SIN-03", 70)], 60, "SEC-N1", "0.52", "0.146", "14.4"),
    (D(2025, 4, 21), [("KAR-12", 72), ("TIO-02", 70)], 66, "SEC-N3", "0.52", "0.147", "14.1"),
    (D(2025, 4, 28), [("NAP-07", 71), ("SIN-03", 72)], 70, "SEC-N1", "0.52", "0.145", "14.6"),
    (D(2025, 5, 5), [("KAR-12", 70), ("TIO-02", 71)], 78, "SEC-N2", "0.51", "0.146", "14.2"),
    (D(2025, 5, 12), [("NAP-07", 72), ("SIN-03", 70)], 84, "SEC-N3", "0.52", "0.144", "14.8"),
    (D(2025, 5, 19), [("KAR-12", 71), ("TIO-02", 72)], 74, "SEC-N1", "0.51", "0.146", "14.0"),
    (D(2025, 5, 26), [("NAP-07", 70), ("SIN-03", 71)], 88, "SEC-N2", "0.52", "0.143", "14.5"),
    (D(2025, 6, 2), [("KAR-12", 72), ("TIO-02", 70)], 76, "SEC-N3", "0.51", "0.145", "14.3"),
    (D(2025, 6, 16), [("NAP-07", 71), ("SIN-03", 70)], 68, "SEC-N1", "0.51", "0.142", "14.7"),
    (D(2025, 6, 30), [("KAR-12", 70), ("TIO-02", 71)], 60, "SEC-N2", "0.50", "0.140", "14.6"),
    (D(2025, 7, 14), [("NAP-07", 70), ("SIN-03", 72)], 54, "SEC-N3", "0.49", "0.136", "14.9"),
    (D(2025, 7, 21), [("KAR-12", 71), ("TIO-02", 70)], 50, "SEC-N1", "0.48", "0.128", "14.8"),
]

# Cibles mensuelles de kilos seches (Sollwert), FICTIVES : a remplacer par le plan du pilote.
# (article, annee, [12 mois, None = pas de cible])
TARGETS = [
    ("sechee", 2025, [None, None, None, 700, 900, 700, 500, 100, None, None, None, None]),
    ("sechee", 2026, [None, None, None, 650, 900, 1000, 900, 300, None, None, None, None]),
    ("ananas_seche", 2026, [250, 250, 250, None, None, None, None, 120, 250, 250, 450, 300]),
    ("ananas_seche", 2027, [300, 300, 300, 200, None, None, None, None, None, None, None, None]),
    ("coco_sechee", 2026, [None, None, None, None, None, None, 500, 1100, 1100, 1300, 1200, 1100]),
    ("coco_sechee", 2027, [1100, 1100, 1100, 1100, None, None, None, None, None, None, None, None]),
]

# Arrets de ligne FICTIFS. (debut (date absolue ou jours avant aujourd'hui), heure, equipement, cause, heures)
# Le sechoir 2 s'arrete la nuit du 12 au 13 juin (regulation) : il explique le rendement bas de ce sechage.
STOPS = [
    (D(2026, 4, 2), 7, "SEC-N1", "maintenance_preventive", 6),
    (D(2026, 4, 2), 7, "SEC-N2", "maintenance_preventive", 6),
    (D(2026, 4, 2), 13, "SEC-N3", "maintenance_preventive", 6),
    (D(2026, 4, 24), 14, "SEC-N3", "coupure_courant", 4),
    (D(2026, 5, 14), 22, "SEC-N1", "panne_mecanique", 9),
    (D(2026, 5, 28), 9, "CDT-N1", "manque_emballage", 3),
    (D(2026, 6, 13), 2, "SEC-N2", "panne_electrique", 5),
    (D(2026, 6, 25), 8, "EPL-N1", "manque_personnel", 4),
    (D(2026, 7, 9), 15, "SEC-N1", "coupure_courant", 3),
    (D(2026, 8, 20), 7, "SEC-N1", "nettoyage_changement", 8),
    (D(2026, 8, 20), 7, "SEC-N2", "nettoyage_changement", 8),
    (D(2026, 8, 20), 7, "SEC-N3", "nettoyage_changement", 8),
    (100, 7, "SEC-S1", "nettoyage_changement", 6),
    (70, 3, "SEC-S2", "panne_mecanique", 7),
    (45, 16, "SEC-S1", "coupure_courant", 2),
    (33, 10, "CDT-S1", "manque_emballage", 5),
    (20, 1, "SEC-S2", "manque_combustible", 6),
    (12, 18, "SEC-S1", "coupure_courant", 3),
    (5, 9, "RAP-S1", "panne_mecanique", 4),
]

MANGO_FOREIGN_BODY = 3  # carton de ce lot : corps etranger (fragment de noyau), bloque, retrie, debloque
MANGO_LATE_RECEPTION = 4  # reception saisie 5 h apres, tablette indisponible

# Ananas Pain de sucre, usine Sud. (date ou jours avant aujourd'hui, livraisons (parcelle, caisses de 15 kg),
# humidite au controle ou None si pas encore controle). Environ 2 t fraiches par lot, pulpe 40 %, sechage 15 %.
PINEAPPLE_HISTORY = [
    (D(2026, 1, 12), [("ALE-08", 70), ("TIA-11", 63)], "16.2"),
    (D(2026, 1, 26), [("BON-21", 72), ("ALE-08", 61)], "15.8"),
    (D(2026, 2, 9), [("TIA-11", 68), ("BON-21", 65)], "17.1"),
    (D(2026, 2, 23), [("ALE-08", 66), ("TIA-11", 67)], "16.5"),
    (D(2026, 3, 9), [("BON-21", 70), ("ALE-08", 63)], "15.4"),
    (D(2026, 3, 23), [("TIA-11", 71), ("BON-21", 62)], "16.9"),
    (105, [("ALE-08", 69), ("TIA-11", 64)], "16.0"),
    (91, [("BON-21", 70), ("ALE-08", 63)], "17.4"),
    (77, [("TIA-11", 66), ("BON-21", 67)], "15.9"),
    (63, [("ALE-08", 72), ("TIA-11", 61)], "16.7"),
    (49, [("BON-21", 68), ("ALE-08", 65)], "16.3"),
    (35, [("TIA-11", 70), ("BON-21", 63)], "17.0"),
    (21, [("ALE-08", 67), ("TIA-11", 66)], "16.1"),
    (9, [("BON-21", 71), ("ALE-08", 62)], None),
]
PINEAPPLE_LATE_DRYING = 9  # sechage declare le lendemain matin (oubli)
# Lot en conversion seche a part (jamais melange au bio) : (jours avant aujourd'hui, caisses, humidite)
PINEAPPLE_CONVERSION = (56, 80, "16.6")

# Coco rapee, usine Sud. (jours avant aujourd'hui, parcelle, sacs de 50 kg, humidite au controle).
COCONUT_HISTORY = [
    (130, "GRB-06", 50, "2.8"), (112, "JAC-04", 50, "2.6"), (95, "GRB-06", 48, "2.9"), (78, "JAC-04", 50, "2.7"),
    (60, "GRB-06", 52, "2.5"), (42, "JAC-04", 50, "2.9"), (25, "GRB-06", 50, "2.8"), (11, "JAC-04", 49, "2.6"),
]
COCONUT_LATE_RECEPTION = 3  # fiche papier ressaisie le lendemain


def _at(day, hour=9, minute=0):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))


def _container(serial):
    """Numero de conteneur fictif au format ISO 6346, avec son chiffre de controle."""
    first = f"TRCU{serial}"
    return f"{first}{container_check_digit(first)}"


def _kg(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_DOWN)


class SimulatedClock:
    """Horloge de la demo : remplace django.utils.timezone.now pendant la creation, puis rend l'heure reelle.

    Ne sert qu'a dater les saisies de l'historique comme si elles avaient ete faites au fil de la saison.
    Elle n'avance jamais au-dela de l'heure reelle.
    """

    def __init__(self):
        self._real = timezone.now
        self.limit = self._real()
        self.current = None

    def __enter__(self):
        timezone.now = self._now
        return self

    def __exit__(self, *exc):
        timezone.now = self._real
        return False

    def _now(self):
        return self.current if self.current is not None else self._real()

    def set(self, when):
        self.current = min(when, self.limit)


class Command(BaseCommand):
    help = "Cree une entreprise de demonstration « fruits seches bio » avec ses comptes et une saison d'historique."

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
        self.boxes = {}  # site -> [lot de cartons vides, cartons restants, date de livraison]
        self.clock = None

    @property
    def op(self):
        return self.users[User.Role.OPERATEUR]

    @property
    def prod(self):
        return self.users[User.Role.PRODUCTION]

    @property
    def qa(self):
        return self.users[User.Role.QUALITE]

    def _when(self, at, delay=15, late=None):
        """Heure de saisie : quelques minutes apres le geste, ou bien plus tard pour une saisie tardive."""
        if late:
            self.clock.set(at + late[1])
            return {"late_reason_code": late[0]}
        self.clock.set(at + delay * MIN)
        return {}

    # Comptes et referentiels ------------------------------------------------------

    def _accounts(self, at):
        self.clock.set(at)
        username, _, first, last, job = ACCOUNTS[0]
        tenants.update_user(tenant_id=self.t, user=self.admin, target=self.admin, first_name=first, last_name=last,
                            job_title=job)
        self.users["admin"] = self.admin
        for username, role, first, last, job in ACCOUNTS[1:]:
            self.users[role] = tenants.create_user(
                tenant_id=self.t, user=self.admin, username=username, password=self.password, role=role,
                first_name=first, last_name=last, job_title=job, manager=self.admin,
            )

    def _catalog(self):
        t, u = self.t, self.admin
        absent = {c: "absent" for c in allergen_codes()}
        a = {}

        def article(key, code, name, kind, unit="kg", conversion=None, band=None, **extra):
            if kind == "matiere":
                extra["allergens"] = absent
            if band:
                extra["yield_min_pct"], extra["yield_max_pct"] = Decimal(band[0]), Decimal(band[1])
            a[key] = catalog.create_article(tenant_id=t, user=u, code=code, name=name, article_type=kind,
                                            base_unit=unit, storage="" if kind == "emballage" else "ambiant", **extra)
            if conversion:
                catalog.create_conversion(tenant_id=t, user=u, article=a[key], unit_name=conversion[0],
                                          factor=Decimal(conversion[1]))

        article("mangue", "MGAF", "Mangue Amélie fraîche", "matiere", conversion=("caisse", "20"))
        # Perte de poids au murissement : fourchette FICTIVE, a remplacer par celle du pilote.
        article("mure", "MGAM", "Mangue Amélie mûre", "matiere", band=("95", "100"))
        article("lavee", "MGAL", "Mangue lavée et triée", "semi_fini", shelf_life_days=2)
        article("pulpe", "MGAD", "Mangue épluchée en tranches", "semi_fini", shelf_life_days=1)
        # Bilan de matiere seche : pulpe a 83,5 % d'eau (USDA), sechee a 14 % : 19,2 % au plus, sans aucune perte.
        article("sechee", "MGAS", "Mangue Amélie séchée en vrac", "semi_fini", shelf_life_days=365,
                band=("14", "19"))
        article("triee", "MGAT", "Mangue séchée triée", "semi_fini", shelf_life_days=365)
        article("carton", "MGAC", "Mangue séchée, carton vrac 10 kg", "fini", conversion=("carton", "10"),
                shelf_life_days=365)
        article("palette", "MGAP", "Mangue séchée, palette de cartons", "fini", shelf_life_days=365)
        article("ananas", "ANAF", "Ananas Pain de sucre frais", "matiere", conversion=("caisse", "15"))
        article("ananas_lave", "ANAL", "Ananas lavé", "semi_fini", shelf_life_days=2)
        article("ananas_epluche", "ANAP", "Ananas épluché tranché", "semi_fini", shelf_life_days=1)
        # Pulpe a 86 % d'eau (USDA), sechee a 16 % : 16,7 % au plus.
        article("ananas_seche", "ANAS", "Ananas séché en vrac", "semi_fini", shelf_life_days=365, band=("13", "17"))
        article("ananas_carton", "ANAC", "Ananas séché, carton vrac 10 kg", "fini", conversion=("carton", "10"),
                shelf_life_days=365)
        article("coco", "COCF", "Noix de coco décortiquée", "matiere", conversion=("sac", "50"))
        article("coco_amande", "COCA", "Amande de coco écalée", "semi_fini", shelf_life_days=2)
        article("coco_paree", "COCB", "Amande de coco parée", "semi_fini", shelf_life_days=2)
        article("coco_rapee", "COCR", "Coco râpée humide", "semi_fini", shelf_life_days=1)
        # Chair a 47 % d'eau (USDA), sechee a 3 % : 54,6 % au plus.
        article("coco_sechee", "COCS", "Coco râpée séchée en vrac", "semi_fini", shelf_life_days=365,
                band=("50", "55"))
        article("coco_froide", "COCT", "Coco râpée séchée refroidie", "semi_fini", shelf_life_days=365)
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
            ("LAV-N1", "Bac de lavage Nord", "preparation", nord),
            ("TRI-N1", "Table de tri Nord", "tri", nord),
            ("EPL-N1", "Table d'épluchage Nord", "preparation", nord),
            ("PRT-N1", "Bac de trempage Nord", "preparation", nord),
            ("SEC-N1", "Séchoir tunnel Nord 1", "sechoir", nord),
            ("SEC-N2", "Séchoir tunnel Nord 2", "sechoir", nord),
            ("SEC-N3", "Séchoir tunnel Nord 3", "sechoir", nord),
            ("TRF-N1", "Table de tri finition Nord", "tri", nord),
            ("CDT-N1", "Ligne de conditionnement Nord", "conditionnement", nord),
            ("LAV-S1", "Bac de lavage Sud", "preparation", sud),
            ("PRE-S1", "Table d'épluchage Sud", "preparation", sud),
            ("SEC-S1", "Séchoir Sud 1 (ananas)", "sechoir", sud),
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

    # Saisies ----------------------------------------------------------------------

    def _receive(self, article, parcel, count, at, site, unit="caisse", visual_ok=True, reason_code="",
                 temperature="29.5", late=None):
        parcel = self.parcels[parcel]
        return services.receive_lot(
            tenant_id=self.t, user=self.op, article=article, supplier=parcel.producer, supplier_lot_code="",
            parcel=parcel, quantity=Decimal(count), unit=unit, date_type="ddm",
            # Fruit frais : date courte, simple repere de fraicheur.
            expiry_date=at.date() + datetime.timedelta(days=10), visual_ok=visual_ok, reason_code=reason_code,
            temperature_c=Decimal(temperature), occurred_at=at, site=site, **self._when(at, late=late),
        )

    def _run(self, step, equipment, inputs, article, quantity, start, end, unit=None, waste=None, user=None,
             late=None):
        return production.declare_run(
            tenant_id=self.t, user=user or self.prod, step=step, equipment=equipment,
            inputs=[(lot, Decimal(q)) for lot, q in inputs], output_article=article, output_quantity=Decimal(quantity),
            output_unit=unit, started_at=start, ended_at=end,
            waste_quantity=Decimal(waste[0]) if waste else None, waste_code=waste[1] if waste else "",
            waste_comment=waste[2] if waste and len(waste) > 2 else "", **self._when(end, delay=20, late=late),
        ).output_lot

    def _qc(self, lot, at, moisture, failed=(), comment=""):
        return services.record_quality_check(
            tenant_id=self.t, user=self.qa, lot_id=lot.id, moisture_pct=Decimal(moisture),
            checks={code: "nok" if code in failed else "ok" for code in QUALITY_CRITERIA}, comment=comment,
            checked_at=at, **self._when(at, delay=10),
        )

    def _ship(self, lines, at, customer, serial, site, bl=True):
        return shipping.create_shipment(
            tenant_id=self.t, user=self.prod, customer=customer, lines=lines, shipped_at=at,
            container_number=_container(serial), seal_number=f"SCELLE-DEMO-{serial}",
            export_document_ref=f"COI.CI.2026.DEMO-{serial}", bill_of_lading=f"BL-DEMO-{serial}" if bl else "",
            site=site, **self._when(at, delay=40),
        )

    def _boxes_for(self, site, n, at):
        """Lot de cartons vides de l'usine avec assez de cartons. Nouvelle livraison (6 paquets de 50) au besoin."""
        current = self.boxes.get(site.id)
        if current is None or current[1] < n or current[2] > at:
            day = at - 24 * H
            lot = services.receive_lot(
                tenant_id=self.t, user=self.op, article=self.a["carton_vide"], supplier=self.p["emballages"],
                supplier_lot_code=f"EL-{day:%y%m%d}-{site.name[6]}", quantity=Decimal("6"), unit="paquet",
                occurred_at=day, site=site, **self._when(day),
            )
            current = self.boxes[site.id] = [lot, 300, day]
        current[1] -= n
        return current[0]

    def _pack(self, dried, kg, article, at, equipment, site, cartons=None):
        """Conditionnement en cartons de 10 kg. Le reste (moins de 10 kg) part en chutes."""
        n = cartons if cartons is not None else int(kg // 10)
        rest = kg - n * 10
        boxes = self._boxes_for(site, n, at)
        return self._run("conditionnement", equipment, [(dried, str(kg)), (boxes, str(n))], article, str(n), at,
                         at + 3 * H, unit="carton", waste=(str(rest), "chutes") if rest else None)

    # Mangue -------------------------------------------------------------------------

    def _mango_batch(self, i, row, nord):
        a, e = self.a, self.e
        day, deliveries, wait, dryer, pulp, dry, moisture = row
        lots = []
        for j, (parcel, caisses) in enumerate(deliveries):
            late = ("tablette_indisponible", 5 * H) if i == MANGO_LATE_RECEPTION and j == 0 else None
            lots.append(self._receive(a["mangue"], parcel, str(caisses), _at(day, 7, 10 + 25 * j), nord, late=late))
        if i == 5:
            # Saisie en double a la reception, annulee aussitot par le receptionnaire (contre-mouvement, motif code).
            twice = self._receive(a["mangue"], deliveries[0][0], str(deliveries[0][1]), _at(day, 7, 10), nord)
            self.clock.set(_at(day, 8, 5))
            entry = Movement.objects.get(lot=twice, movement_type=Movement.Type.RECEPTION)
            services.reverse_movement(tenant_id=self.t, user=self.op, movement_id=entry.id, reason_code="doublon")
        fresh = sum(c for _, c in deliveries) * 20
        ripe_kg = _kg(fresh * Decimal("0.98"))
        ripe_end = _at(day + datetime.timedelta(days=3), 7)
        ripe = self._run("murissement", e["MUR-N1"], [(lot, str(c * 20)) for lot, (_, c) in zip(lots, deliveries)],
                         a["mure"], str(ripe_kg), _at(day, 9), ripe_end)
        peel_start = ripe_end + wait * H
        pulp_kg = _kg(ripe_kg * Decimal(pulp))
        peeled = self._run("epluchage_decoupe", e["EPL-N1"], [(ripe, str(ripe_kg))], a["pulpe"], str(pulp_kg),
                           peel_start, peel_start + 6 * H, waste=(str(ripe_kg - pulp_kg), "peaux_noyaux"))
        dry_start = peel_start + 7 * H
        dried_kg = _kg(pulp_kg * Decimal(dry))
        dried = self._run("sechage", e[dryer], [(peeled, str(pulp_kg))], a["sechee"], str(dried_kg), dry_start,
                          dry_start + 20 * H)
        pack_at = dry_start + 22 * H
        carton = self._pack(dried, dried_kg, a["carton"], pack_at, e["CDT-N1"], nord)
        check_at = pack_at + 4 * H
        if i == MANGO_FOREIGN_BODY:
            # Fragment de noyau trouve : lot bloque automatiquement, retrie, debloque apres double validation
            # (Qualite demande, Production valide), puis nouveau controle conforme.
            self._qc(carton, check_at, moisture, failed=("corps_etrangers",))
            self.clock.set(check_at + 2 * H)
            req = services.request_approval(tenant_id=self.t, user=self.qa, lot_id=carton.id, action="release",
                                            reason_code="cause_corrigee")
            self.clock.set(check_at + 5 * H)
            services.approve_request(tenant_id=self.t, user=self.prod, request_id=req.id)
            self._qc(carton, check_at + 6 * H, moisture)
        else:
            self._qc(carton, check_at, moisture)
        return carton

    def _mango_2025(self, nord):
        """Saison 2025 : meme chaine que 2026, tout est expedie avant la saison suivante."""
        p = self.p
        cartons = [self._mango_batch(100 + i, row, nord) for i, row in enumerate(MANGO_2025)]

        def lines(indexes):
            return [(cartons[i], Decimal(cartons[i].production_run.output_quantity), None) for i in indexes]

        self._ship(lines([0, 1, 2, 3]), _at(D(2025, 5, 30), 7), p["rotterdam"], "250500", nord)
        self._ship(lines([4, 5, 6, 7]), _at(D(2025, 6, 27), 7), p["lyon"], "250600", nord)
        self._ship(lines([8, 9, 10, 11]), _at(D(2025, 8, 8), 7), p["hambourg"], "250800", nord)

    def _targets(self):
        for key, year, months in TARGETS:
            dashboard.set_targets(tenant_id=self.t, user=self.admin, article=self.a[key], year=year,
                                  months=[None if m is None else Decimal(m) for m in months])

    def _stops(self, today):
        """Arrets de la saison, declares au fil de l'eau, plus un arret en cours (cartons vides attendus)."""
        users = {"CDT": self.op, "EPL": self.op, "RAP": self.op}
        for when, hour, code, cause, hours in STOPS:
            day = when if isinstance(when, D) else today - datetime.timedelta(days=when)
            start = _at(day, hour)
            end = start + hours * H
            self.clock.set(end + 10 * MIN)
            production.declare_stop(tenant_id=self.t, user=users.get(code[:3], self.prod), equipment=self.e[code],
                                    cause_code=cause, started_at=start, ended_at=end)
        self.clock.set(self.clock.limit)
        production.declare_stop(tenant_id=self.t, user=self.op, equipment=self.e["CDT-S1"],
                                cause_code="manque_emballage", started_at=self.clock.limit - H)

    def _mango(self, nord, sud):
        a, e, p = self.a, self.e, self.p
        cartons = [self._mango_batch(i, row, nord) for i, row in enumerate(MANGO_HISTORY)]

        # Lot du 9 juin, montre en direct : trois parcelles bio, toutes les etapes du parcours, deux sechoirs.
        day = D(2026, 6, 9)
        r1 = self._receive(a["mangue"], "NAP-07", "75", _at(day, 7, 5), nord, temperature="28.5")
        r2 = self._receive(a["mangue"], "SIN-03", "70", _at(day, 7, 30), nord, temperature="29.0")
        r3 = self._receive(a["mangue"], "KAR-12", "75", _at(day, 7, 55), nord, temperature="29.5")
        # Livraison refusee (piqures de mouche des fruits) : bloquee a la reception, detruite apres double validation.
        bad = self._receive(a["mangue"], "NIO-05", "40", _at(day, 8, 20), nord, visual_ok=False,
                            reason_code="contamination", temperature="31.0")
        self.clock.set(_at(day, 9, 30))
        req = services.request_approval(tenant_id=self.t, user=self.qa, lot_id=bad.id, action="destroy",
                                        reason_code="contamination")
        self.clock.set(_at(day, 10, 15))
        services.approve_request(tenant_id=self.t, user=self.prod, request_id=req.id)

        mure = self._run("murissement", e["MUR-N1"], [(r1, "1500"), (r2, "1400"), (r3, "1500")], a["mure"], "4312",
                         _at(day, 9), _at(day + datetime.timedelta(days=3), 7))
        d12 = day + datetime.timedelta(days=3)
        lavee = self._run("lavage", e["LAV-N1"], [(mure, "4312")], a["lavee"], "4300", _at(d12, 7, 30),
                          _at(d12, 9), waste=("12", "fruits_abimes"), user=self.op)
        triee = self._run("tri", e["TRI-N1"], [(lavee, "4300")], a["lavee"], "4170", _at(d12, 9), _at(d12, 11),
                          waste=("130", "fruits_abimes"), user=self.op)
        pulp1 = self._run("epluchage_decoupe", e["EPL-N1"], [(triee, "2085")], a["pulpe"], "1105", _at(d12, 11),
                          _at(d12, 15), waste=("980", "peaux_noyaux"))
        pulp2 = self._run("epluchage_decoupe", e["EPL-N1"], [(triee, "2085")], a["pulpe"], "1084", _at(d12, 12),
                          _at(d12, 16), waste=("1001", "peaux_noyaux"))
        # Trempage au jus de citron (pas de sulfites en bio) : un peu d'egouttage.
        pre1 = self._run("pretraitement", e["PRT-N1"], [(pulp1, "1105")], a["pulpe"], "1100", _at(d12, 15),
                         _at(d12, 16), waste=("5", "chutes"))
        pre2 = self._run("pretraitement", e["PRT-N1"], [(pulp2, "1084")], a["pulpe"], "1080", _at(d12, 16),
                         _at(d12, 17), waste=("4", "chutes"))
        d13 = d12 + datetime.timedelta(days=1)
        sec1 = self._run("sechage", e["SEC-N1"], [(pre1, "1100")], a["sechee"], "165", _at(d12, 17), _at(d13, 13))
        # Sechoir 2 : 13 % de la pulpe, sous la fourchette (14 a 19 %). Ecart signale au bilan matiere.
        sec2 = self._run("sechage", e["SEC-N2"], [(pre2, "1080")], a["sechee"], "140", _at(d12, 18), _at(d13, 14))
        t1 = self._run("tri_finition", e["TRF-N1"], [(sec1, "165")], a["triee"], "162", _at(d13, 15), _at(d13, 17),
                       waste=("3", "chutes"))
        t2 = self._run("tri_finition", e["TRF-N1"], [(sec2, "140")], a["triee"], "137", _at(d13, 15, 30),
                       _at(d13, 17, 30), waste=("3", "chutes"))
        d15 = d13 + datetime.timedelta(days=2)
        c1 = self._pack(t1, 162, a["carton"], _at(d15, 8), e["CDT-N1"], nord)
        c2 = self._pack(t2, 137, a["carton"], _at(d15, 12), e["CDT-N1"], nord)
        self._qc(c1, _at(d15, 12), "14.1")
        self._qc(c2, _at(d15, 16), "14.6")
        pal = self._run("palettisation", e["CDT-N1"], [(c1, "160"), (c2, "130")], a["palette"], "290",
                        _at(d15 + datetime.timedelta(days=1), 9), _at(d15 + datetime.timedelta(days=1), 10))
        self._ship([(pal, Decimal("290"), None)], _at(D(2026, 7, 6), 7), p["rotterdam"], "260600", nord)

        # Lot du 16 juin : premiere declaration de murissement avec une mauvaise quantite, annulee avec motif.
        # Les mangues reviennent en stock, le lot produit par erreur est bloque, puis la bonne declaration suit.
        day = D(2026, 6, 16)
        r4 = self._receive(a["mangue"], "TIO-02", "70", _at(day, 7, 10), nord)
        r5 = self._receive(a["mangue"], "SIN-03", "73", _at(day, 7, 35), nord)
        d19 = day + datetime.timedelta(days=3)
        erreur = self._run("murissement", e["MUR-N1"], [(r4, "1400"), (r5, "1460")], a["mure"], "2420",
                           _at(day, 9), _at(d19, 7))
        self.clock.set(_at(d19, 7, 50))
        production.cancel_run(tenant_id=self.t, user=self.prod, run_id=erreur.production_run.id,
                              reason_code="mauvaise_quantite")
        mure2 = self._run("murissement", e["MUR-N1"], [(r4, "1400"), (r5, "1460")], a["mure"], "2803",
                          _at(day, 9), _at(d19, 7, 45))
        tri2 = self._run("tri", e["TRI-N1"], [(mure2, "2803")], a["lavee"], "2720", _at(d19, 8), _at(d19, 10),
                         waste=("83", "fruits_abimes"), user=self.op)
        pulp3 = self._run("epluchage_decoupe", e["EPL-N1"], [(tri2, "2720")], a["pulpe"], "1414", _at(d19, 10),
                          _at(d19, 16), waste=("1306", "peaux_noyaux"))
        d20 = d19 + datetime.timedelta(days=1)
        sec3 = self._run("sechage", e["SEC-N3"], [(pulp3, "1414")], a["sechee"], "212", _at(d19, 17), _at(d20, 13))
        tri3 = self._run("tri_finition", e["TRF-N1"], [(sec3, "212")], a["triee"], "208", _at(d20, 14),
                         _at(d20, 16), waste=("4", "chutes"))
        c3 = self._pack(tri3, 208, a["carton"], _at(d20 + datetime.timedelta(days=2), 8), e["CDT-N1"], nord)
        self._qc(c3, _at(d20 + datetime.timedelta(days=2), 12), "13.9")
        self._ship([(c3, Decimal("8"), "carton")], _at(D(2026, 7, 9), 7), p["lyon"], "260700", nord)

        # Expeditions de la saison, en groupage (LCL) : quelques centaines de cartons par client et par mois.
        def lines(indexes):
            return [(cartons[i], Decimal(cartons[i].production_run.output_quantity), None) for i in indexes]

        self._ship(lines([0, 1, 2]), _at(D(2026, 5, 8), 7), p["rotterdam"], "260500", nord)
        self._ship(lines([3, 4, 5]), _at(D(2026, 5, 29), 7), p["lyon"], "260501", nord)
        self._ship(lines([6, 7]), _at(D(2026, 6, 19), 7), p["hambourg"], "260601", nord)
        self._ship(lines([8, 9, 10]), _at(D(2026, 7, 24), 7), p["rotterdam"], "260701", nord)
        # Sans connaissement (BL) : l'expedition passe en jaune au tableau de bord.
        self._ship(lines([11, 12]), _at(D(2026, 8, 14), 7), p["hambourg"], "260800", nord, bl=False)
        return {"c2": c2, "bad": bad, "last": cartons[-1], "c3": c3}

    # Ananas -------------------------------------------------------------------------

    def _pineapple_batch(self, i, day, deliveries, moisture, sud):
        a, e = self.a, self.e
        lots = [self._receive(a["ananas"], parcel, str(c), _at(day, 7, 10 + 20 * j), sud, temperature="27.5")
                for j, (parcel, c) in enumerate(deliveries)]
        fresh = sum(c for _, c in deliveries) * 15
        washed = _kg(fresh * Decimal("0.995"))
        lave = self._run("lavage", e["LAV-S1"], [(lot, str(c * 15)) for lot, (_, c) in zip(lots, deliveries)],
                         a["ananas_lave"], str(washed), _at(day, 8, 30), _at(day, 10),
                         waste=(str(fresh - washed), "fruits_abimes"), user=self.op)
        flesh = _kg(washed * Decimal("0.40"))
        peeled = self._run("epluchage_decoupe", e["PRE-S1"], [(lave, str(washed))], a["ananas_epluche"], str(flesh),
                           _at(day, 10, 30), _at(day, 15), waste=(str(washed - flesh), "peaux_noyaux"))
        dried_kg = _kg(flesh * Decimal("0.15"))
        next_day = day + datetime.timedelta(days=1)
        late = ("oubli", 10 * H) if i == PINEAPPLE_LATE_DRYING else None
        dried = self._run("sechage", e["SEC-S1"], [(peeled, str(flesh))], a["ananas_seche"], str(dried_kg),
                          _at(day, 16), _at(next_day, 10), late=late)
        carton = self._pack(dried, dried_kg, a["ananas_carton"], _at(next_day, 11), e["CDT-S1"], sud)
        if moisture:
            self._qc(carton, _at(next_day, 15), moisture)
        return carton

    def _pineapple(self, nord, sud, today):
        a, e, p = self.a, self.e, self.p
        cartons = []
        for i, (when, deliveries, moisture) in enumerate(PINEAPPLE_HISTORY):
            day = when if isinstance(when, D) else today - datetime.timedelta(days=when)
            cartons.append(self._pineapple_batch(i, day, deliveries, moisture, sud))

        def lines(indexes):
            return [(cartons[i], Decimal(cartons[i].production_run.output_quantity), None) for i in indexes]

        self._ship(lines([0, 1, 2]), _at(D(2026, 2, 20), 7), p["lyon"], "260200", sud)
        self._ship(lines([3, 4, 5]), _at(D(2026, 4, 3), 7), p["rotterdam"], "260400", sud)
        self._ship(lines([6, 7, 8]), _at(today - datetime.timedelta(days=60), 7), p["lyon"], "261000", sud)
        self._ship(lines([9, 10, 11]), _at(today - datetime.timedelta(days=28), 7), p["hambourg"], "261100", sud)
        self._ship(lines([12]), _at(today - datetime.timedelta(days=14), 7), p["rotterdam"], "261101", sud)

        # Producteur en conversion : seche a part, jamais melange au bio, controle et garde en stock.
        ago, caisses, moisture = PINEAPPLE_CONVERSION
        day = today - datetime.timedelta(days=ago)
        conv = self._receive(a["ananas"], "ADI-02", str(caisses), _at(day, 7, 30), sud)
        fresh = caisses * 15
        lave = self._run("lavage", e["LAV-S1"], [(conv, str(fresh))], a["ananas_lave"], str(fresh - 6),
                         _at(day, 8, 30), _at(day, 9, 30), waste=("6", "fruits_abimes"), user=self.op)
        flesh = _kg((fresh - 6) * Decimal("0.40"))
        peeled = self._run("epluchage_decoupe", e["PRE-S1"], [(lave, str(fresh - 6))], a["ananas_epluche"],
                           str(flesh), _at(day, 10), _at(day, 13), waste=(str(fresh - 6 - flesh), "peaux_noyaux"))
        dried_kg = _kg(flesh * Decimal("0.15"))
        dried = self._run("sechage", e["SEC-S1"], [(peeled, str(flesh))], a["ananas_seche"], str(dried_kg),
                          _at(day, 14), _at(day + datetime.timedelta(days=1), 8))
        conv_carton = self._pack(dried, dried_kg, a["ananas_carton"], _at(day + datetime.timedelta(days=1), 9),
                                 e["CDT-S1"], sud)
        self._qc(conv_carton, _at(day + datetime.timedelta(days=1), 13), moisture)

        # Lot montre en direct, recu avant-hier : 3 t de la parcelle BON-21, 2,4 t traitees (un cycle de sechoir),
        # le reste attend. Le lot seche attend l'analyse de residus de pesticides : bloque, a debloquer en direct.
        day = today - datetime.timedelta(days=2)
        r6 = self._receive(a["ananas"], "BON-21", "200", _at(day, 7, 5), sud, temperature="27.0")
        conv2 = self._receive(a["ananas"], "ADI-02", "40", _at(day, 7, 40), sud, temperature="27.5")
        lave = self._run("lavage", e["LAV-S1"], [(r6, "2400")], a["ananas_lave"], "2388", _at(day, 8, 30),
                         _at(day, 10), waste=("12", "fruits_abimes"), user=self.op)
        peeled = self._run("epluchage_decoupe", e["PRE-S1"], [(lave, "2388")], a["ananas_epluche"], "955",
                           _at(day, 10, 30), _at(day, 15), waste=("1433", "peaux_noyaux"))
        dry = self._run("sechage", e["SEC-S1"], [(peeled, "955")], a["ananas_seche"], "143", _at(day, 16),
                        _at(day + datetime.timedelta(days=1), 10))
        # Cartons vides envoyes de l'usine Nord vers l'usine Sud : transfert d'une partie du lot.
        boxes = self._boxes_for(nord, 30, _at(day, 6))
        services.transfer_lot(tenant_id=self.t, user=self.prod, lot_id=boxes.id, to_site=sud,
                              quantity=Decimal("30"), occurred_at=_at(day, 6), **self._when(_at(day, 6)))
        self.clock.set(_at(day + datetime.timedelta(days=1), 10, 40))
        services.block_lot(tenant_id=self.t, user=self.qa, lot_id=dry.id, reason_code="autre",
                           comment="En attente du résultat d'analyse de résidus de pesticides")
        # Echantillon de 1 kg envoye au laboratoire : rebut sous double validation.
        req = services.request_approval(tenant_id=self.t, user=self.qa, lot_id=dry.id, action="scrap",
                                        reason_code="echantillon", quantity=Decimal("1"))
        self.clock.set(_at(day + datetime.timedelta(days=1), 11, 30))
        services.approve_request(tenant_id=self.t, user=self.prod, request_id=req.id)
        # Demande d'ajustement d'inventaire refusee : le recomptage n'est pas termine.
        self.clock.set(_at(day + datetime.timedelta(days=1), 12))
        req = services.request_approval(tenant_id=self.t, user=self.prod, lot_id=conv2.id, action="adjust",
                                        reason_code="ecart_inventaire", quantity=Decimal("-15"))
        self.clock.set(_at(day + datetime.timedelta(days=1), 14))
        services.reject_request(tenant_id=self.t, user=self.qa, request_id=req.id, reason_code="verification_en_cours")
        return {"r6": r6, "conv": conv2, "dry": dry, "unchecked": cartons[-1], "conv_carton": conv_carton}

    # Coco -------------------------------------------------------------------------

    def _coconut_chain(self, lot, kg, start, ratios, sud):
        """Cassage, parage, rapage, pasteurisation, sechage, refroidissement. Renvoie (lot refroidi, kg, heure)."""
        a, e = self.a, self.e
        steps = [
            ("cassage", "CAS-S1", "coco_amande", ratios[0], 3, ("autre", "Coques et eau de coco")),
            ("parage", "CAS-S1", "coco_paree", ratios[1], 3, ("autre", "Pellicule brune retirée au parage")),
            ("rapage", "RAP-S1", "coco_rapee", "0.995", 1, ("chutes",)),
            ("pasteurisation", "PAS-S1", "coco_rapee", "0.995", 1, ("chutes",)),
            ("sechage", "SEC-S2", "coco_sechee", ratios[2], 12, None),
            ("refroidissement", "REF-S1", "coco_froide", "0.995", 2, ("chutes",)),
        ]
        current, qty, at = lot, Decimal(kg), start
        for step, equipment, article, ratio, hours, waste in steps:
            out = _kg(qty * Decimal(ratio))
            w = (str(qty - out), *waste) if waste and qty > out else None
            current = self._run(step, e[equipment], [(current, str(qty))], a[article], str(out), at, at + hours * H,
                                waste=w)
            at, qty = at + hours * H, out
        return current, qty, at

    def _coconut(self, sud, today):
        a, p = self.a, self.p
        cartons = []
        for i, (ago, parcel, sacs, moisture) in enumerate(COCONUT_HISTORY):
            day = today - datetime.timedelta(days=ago)
            late = ("ressaisie_papier", 26 * H) if i == COCONUT_LATE_RECEPTION else None
            lot = self._receive(a["coco"], parcel, str(sacs), _at(day, 7, 30), sud, unit="sac", late=late)
            cooled, qty, at = self._coconut_chain(lot, sacs * 50, _at(day, 8), ("0.50", "0.85", "0.53"), sud)
            carton = self._pack(cooled, qty, a["coco_carton"], at + H, self.e["CDT-S1"], sud)
            self._qc(carton, at + 5 * H, moisture)
            cartons.append(carton)

        def lines(indexes):
            return [(cartons[i], Decimal(cartons[i].production_run.output_quantity), None) for i in indexes]

        self._ship(lines([0, 1]), _at(today - datetime.timedelta(days=100), 7), p["hambourg"], "260801", sud)
        self._ship(lines([2, 3]), _at(today - datetime.timedelta(days=65), 7), p["hambourg"], "260901", sud)
        self._ship(lines([4, 5]), _at(today - datetime.timedelta(days=20), 7), p["hambourg"], "261102", sud)

        # Lot d'octobre montre en direct : un carton conforme part a Hambourg, le second est trop humide (4,2 % pour
        # 3 % au plus, norme APCC) : controle non conforme, lot bloque automatiquement.
        day = D(2026, 10, 6)
        coco = self._receive(a["coco"], "JAC-04", "60", _at(day, 7, 30), sud, unit="sac")
        cooled, qty, at = self._coconut_chain(coco, 3000, _at(day, 8), ("0.50", "0.85", "0.53"), sud)
        k1 = self._pack(cooled, 300, a["coco_carton"], at + H, self.e["CDT-S1"], sud)
        k2 = self._pack(cooled, qty - 300, a["coco_carton"], at + 4 * H, self.e["CDT-S1"], sud)
        self._qc(k1, at + 5 * H, "2.8")
        self._qc(k2, at + 8 * H, "4.2", failed=("humidite",))
        self._ship([(k1, Decimal("30"), "carton")], _at(D(2026, 10, 20), 7), p["hambourg"], "260900", sud)
        return {"k2": k2}

    # Tout ---------------------------------------------------------------------------

    def build(self):
        with SimulatedClock() as clock:
            self.clock = clock
            today = timezone.localdate(clock.limit)
            self._accounts(_at(D(2025, 3, 3), 8))
            self.a, self.p = self._catalog()
            self._steps_and_routes(self.a)
            sites, self.e = self._sites()
            nord, sud = sites["nord"], sites["sud"]
            # Seuil propre a l'entreprise (ecran Seuils) : saisies tardives tolerees jusqu'a 3 %, rouge a 10 %.
            dashboard.set_threshold(tenant_id=self.t, user=self.admin, code="late_entries_pct", green="3", red="10")

            self._targets()
            self._mango_2025(nord)
            mango = self._mango(nord, sud)
            pineapple = self._pineapple(nord, sud, today)
            coconut = self._coconut(sud, today)

            # Demande en attente depuis avant-hier apres-midi : 2 cartons ecrases au chariot, rebut demande par le
            # receptionnaire. Elle attend plus de 24 h : jaune au tableau de bord le jour de la demo.
            clock.set(_at(today - datetime.timedelta(days=2), 16))
            services.request_approval(tenant_id=self.t, user=self.op, lot_id=mango["last"].id, action="scrap",
                                      reason_code="emballage_abime", quantity=Decimal("20"))
            self._stops(today)
            clock.set(clock.limit)
        assert timezone.now is clock._real
        return [
            f"Rappel depuis un carton (séchoir 2, écart de rendement) : cherche {mango['c2'].code}",
            f"Rappel depuis un conteneur : cherche {_container('260600')}",
            f"Mélange refusé en direct : épluche ensemble {pineapple['r6'].code} (bio) et "
            f"{pineapple['conv'].code} (en conversion)",
            f"Lot bloqué à débloquer en direct (analyse de résidus) : {pineapple['dry'].code}",
            "Coco râpée, rappel depuis un conteneur : cherche TRCU2609002",
            f"Contrôle qualité non conforme (humidité), lot bloqué : {coconut['k2'].code}",
            f"Lot détruit après double validation : {mango['bad'].code}",
            f"Rebut en attente de validation : {mango['last'].code} (2 cartons écrasés)",
            "Arrêt en cours à terminer en direct : CDT-S1 (manque de cartons vides), écran Arrêts de ligne",
        ]
