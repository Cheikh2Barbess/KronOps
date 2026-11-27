"""Listes fermees de la declaration de production (le moins de texte libre possible)."""

from lots.reasons import OTHER

WASTE = {
    "peaux_noyaux": "Peaux et noyaux",
    "fruits_abimes": "Fruits abîmés ou pourris écartés",
    "declasses": "Produit déclassé (hors calibre, couleur)",
    "chutes": "Chutes et miettes",
    OTHER: "Autre (préciser)",
}

# Annulation d'une declaration (sous-ensemble des motifs d'annulation de mouvement, memes codes).
RUN_CANCEL = {
    "erreur_saisie": "Erreur de saisie",
    "mauvais_lot": "Mauvais lot consommé",
    "mauvaise_quantite": "Mauvaise quantité",
    "doublon": "Déclaration en double",
    OTHER: "Autre (préciser)",
}
