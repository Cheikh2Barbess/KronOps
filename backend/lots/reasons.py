"""Motifs codes (listes fermees). Regle du proprietaire, 26/11/2026 : le moins de texte libre possible.

Un commentaire libre n'est exige que pour le motif « autre ». Le code est stocke, le libelle est affiche.
"""

from rest_framework.exceptions import ValidationError

OTHER = "autre"

BLOCK = {
    "contamination": "Contamination ou corps étranger",
    "emballage_abime": "Emballage abîmé",
    "etiquetage_non_conforme": "Étiquetage non conforme",
    "date_depassee": "DLC ou DDM dépassée",
    "temperature": "Température non respectée",
    "analyse_non_conforme": "Analyse non conforme",
    "suspicion_allergene": "Suspicion d'allergène",
    "reclamation_client": "Réclamation client",
    OTHER: "Autre (préciser)",
}
# Pose automatiquement par une reception non conforme, jamais choisi a la main.
RECEPTION_NON_CONFORME = "reception_non_conforme"
BLOCK_AUTO = {RECEPTION_NON_CONFORME: "Réception non conforme"}

APPROVAL = {
    "release": {
        "analyse_conforme": "Analyse refaite conforme",
        "controle_conforme": "Nouveau contrôle conforme",
        "cause_corrigee": "Cause du blocage corrigée (tri, réétiquetage)",
        "blocage_erreur": "Blocage fait par erreur",
        OTHER: "Autre (préciser)",
    },
    "destroy": {
        "contamination": "Contamination ou corps étranger",
        "date_depassee": "DLC ou DDM dépassée",
        "analyse_non_conforme": "Analyse non conforme",
        "allergene_non_declare": "Allergène non déclaré",
        "retour_client": "Retour client non réutilisable",
        "decision_autorite": "Décision des autorités",
        OTHER: "Autre (préciser)",
    },
    "scrap": {
        "casse": "Casse ou chute",
        "emballage_abime": "Emballage abîmé",
        "produit_non_conforme": "Produit non conforme",
        "date_depassee": "DLC ou DDM dépassée",
        "perte_manutention": "Perte de manutention ou déversement",
        "echantillon": "Échantillon ou analyse",
        OTHER: "Autre (préciser)",
    },
    "adjust": {
        "ecart_inventaire": "Écart constaté à l'inventaire",
        "erreur_saisie": "Erreur de saisie",
        "erreur_unite": "Erreur d'unité ou de conversion",
        OTHER: "Autre (préciser)",
    },
}

REJECT = {
    "justification_insuffisante": "Justification insuffisante",
    "quantite_incorrecte": "Quantité incorrecte",
    "mauvais_lot": "Mauvais lot",
    "verification_en_cours": "Vérification encore en cours",
    "action_inutile": "Action inutile",
    OTHER: "Autre (préciser)",
}

ALL_APPROVAL_CODES = sorted({code for codes in APPROVAL.values() for code in codes})


def check(codes, code, comment, field="reason_code"):
    """Retourne (code, commentaire nettoye). Commentaire obligatoire pour « autre »."""
    if code not in codes:
        raise ValidationError({field: ["Choisissez un motif dans la liste."]})
    comment = (comment or "").strip()
    if code == OTHER and not comment:
        raise ValidationError({"comment": ["Précisez le motif « Autre »."]})
    return code, comment


def text(codes, code, comment):
    """Texte lisible : libelle, plus le commentaire s'il y en a un."""
    label = {**codes, **BLOCK_AUTO}.get(code, code)
    if code == OTHER:
        return comment
    return f"{label} : {comment}" if comment else label


def as_options(codes):
    return [{"code": c, "label": label} for c, label in codes.items()]
