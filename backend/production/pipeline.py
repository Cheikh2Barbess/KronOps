"""Pipeline fruits seches export en 8 blocs (etude du 27/11/2026) : chaque etape et ou elle se fait dans Tracalys.

Quatre sortes d'etapes :
- TRANSFORMATION : etape de production (consomme des lots, cree un lot). Son activation est celle de StepSetting.
- OBLIGATOIRE : ecran sans lequel la tracabilite casse (reception, rappel...). Toujours actif.
- MODULE : ecran facultatif. Desactive, il disparait du menu et l'API refuse de l'utiliser.
- PREVU : pas encore construit. Affiche avec sa phase, ne s'active pas.

Le catalogue est dans le code (pas de texte libre). Ne jamais retirer un code : des reglages l'utilisent.
"""

from django.db import models
from rest_framework.exceptions import ValidationError


class Kind(models.TextChoices):
    TRANSFORMATION = "transformation", "Étape de production"
    OBLIGATOIRE = "obligatoire", "Écran toujours actif"
    MODULE = "module", "Écran activable"
    PREVU = "prevu", "Prévu"


BLOCKS = [
    (1, "Amont : producteurs, parcelles et certification de groupe"),
    (2, "Récolte, collecte, transport et réception"),
    (3, "Transformation : mûrissement, lavage, épluchage, découpe, prétraitements"),
    (4, "Séchage"),
    (5, "Tri, emballage et stockage"),
    (6, "Analyses de laboratoire"),
    (7, "Documents export, empotage et transport"),
    (8, "Import UE, contrôles et rappel"),
]


def _t(block, step):
    return {"code": step, "block": block, "kind": Kind.TRANSFORMATION, "path": "/production"}


def _o(block, code, label, path):
    return {"code": code, "block": block, "kind": Kind.OBLIGATOIRE, "label": label, "path": path}


def _m(block, code, label, path):
    return {"code": code, "block": block, "kind": Kind.MODULE, "label": label, "path": path}


def _p(block, code, label, phase):
    return {"code": code, "block": block, "kind": Kind.PREVU, "label": label, "phase": phase}


AVANT_SAISON = "Phase 1, avant la saison"
FIN_P1 = "Phase 1, fin de phase"

CATALOG = [
    _o(1, "parcelles", "Producteurs et parcelles (statut bio)", "/referentiels"),
    _p(1, "registre_membres", "Registre des membres du groupe (ICS)", FIN_P1),
    _p(1, "estimation_recolte", "Estimation de récolte par parcelle", FIN_P1),
    _p(1, "inspection_interne", "Inspection interne des membres", "Phase 2"),
    _o(2, "reception", "Réception et création du lot", "/receptions"),
    _p(2, "pesee_tare", "Pesée brute, tare et nombre de caisses", AVANT_SAISON),
    _p(2, "tri_entree", "Tri d'entrée en trois classes", AVANT_SAISON),
    _p(2, "collecte_hors_ligne", "Collecte en brousse hors ligne", "Phase 2"),
    _t(3, "murissement"),
    _t(3, "lavage"),
    _t(3, "tri"),
    _t(3, "preparation"),
    _t(3, "cassage"),
    _t(3, "parage"),
    _t(3, "epluchage_decoupe"),
    _t(3, "rapage"),
    _t(3, "pretraitement"),
    _t(3, "pasteurisation"),
    _t(4, "sechage"),
    _t(4, "refroidissement"),
    _p(4, "releves_sechoir", "Relevés de séchoir (température, humidité)", FIN_P1),
    _p(4, "capteurs_sechoir", "Relevés automatiques par capteurs", "Phase 3"),
    _t(5, "tri_finition"),
    _t(5, "conditionnement"),
    _t(5, "palettisation"),
    _o(5, "controle_qualite", "Contrôle qualité du lot (exigé pour expédier)", "/qualite"),
    _m(5, "transfert", "Transfert entre usines", "/transferts"),
    _p(5, "etiquette_qr", "Étiquette carton avec QR code", FIN_P1),
    _p(5, "detecteur_metaux", "Test du détecteur de métaux", FIN_P1),
    _p(5, "conditions_stockage", "Température et humidité du stockage", FIN_P1),
    _p(6, "analyses_labo", "Demande et résultat d'analyse par lot", AVANT_SAISON),
    _p(6, "plan_echantillonnage", "Plan d'échantillonnage", "Phase 2"),
    _m(7, "expedition", "Empotage et expédition (conteneur, plomb, COI)", "/expeditions"),
    _p(7, "donnees_coi", "Données du COI prêtes pour TRACES", AVANT_SAISON),
    _p(7, "documents_export", "Suivi des documents export", FIN_P1),
    _o(8, "tracabilite", "Recherche amont et aval", "/tracabilite"),
    _o(8, "rappel", "Rapport de rappel", "/rappel"),
    _p(8, "blocage_groupe", "Blocage groupé du périmètre de rappel", AVANT_SAISON),
    _p(8, "reclamation_arrivee", "Réclamation ou refus à l'arrivée", FIN_P1),
]

BY_CODE = {s["code"]: s for s in CATALOG}


def module_active(code):
    """Vrai si le module facultatif est actif pour l'entreprise courante (actif par defaut). RLS : par client."""
    from production.models import PipelineSetting

    setting = PipelineSetting.objects.filter(code=code).first()
    return setting is None or setting.is_active


def require_module(code, field="non_field_errors"):
    if not module_active(code):
        label = BY_CODE[code]["label"]
        raise ValidationError({field: [f"« {label} » est désactivé pour votre entreprise (écran Pipeline)."]})
