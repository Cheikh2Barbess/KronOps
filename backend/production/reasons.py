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

# Arrets de ligne. Chaque cause est planifiee (prevue au planning) ou non planifiee (subie). Liste fermee : une
# precision n'est demandee que pour « Autre ». Ne jamais retirer un code : des arrets l'utilisent.
STOP_CAUSES = {
    "panne_mecanique": "Panne mécanique (ventilateur, moteur, convoyeur)",
    "panne_electrique": "Panne électrique ou de régulation",
    "coupure_courant": "Coupure de courant",
    "manque_combustible": "Manque de gaz ou de combustible",
    "manque_matiere": "Manque de matière à traiter",
    "manque_emballage": "Manque d'emballage",
    "manque_personnel": "Manque de personnel",
    "attente_qualite": "Attente d'une décision qualité",
    "reglage": "Réglage ou mise en route",
    "nettoyage_changement": "Nettoyage ou changement de fruit (planifié)",
    "maintenance_preventive": "Maintenance préventive (planifiée)",
    OTHER: "Autre (préciser)",
}
PLANNED_STOPS = {"nettoyage_changement", "maintenance_preventive"}

# Annulation d'un arret declare par erreur.
STOP_CANCEL = {
    "erreur_saisie": "Erreur de saisie",
    "mauvais_equipement": "Mauvais équipement",
    "doublon": "Arrêt déclaré en double",
    OTHER: "Autre (préciser)",
}
