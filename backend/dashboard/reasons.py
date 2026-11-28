"""Listes fermees du tableau de bord."""

from lots.reasons import OTHER

# Motif d'un changement (ou d'un retrait) d'une cible deja saisie. La premiere saisie n'en demande pas.
TARGET_CHANGE = {
    "erreur_saisie": "Erreur de saisie",
    "prevision_revue": "Prévision revue",
    "matiere_insuffisante": "Matière insuffisante (récolte, approvisionnement)",
    "demande_client": "Demande client modifiée",
    "capacite_modifiee": "Capacité modifiée (équipement, personnel)",
    OTHER: "Autre (préciser)",
}
