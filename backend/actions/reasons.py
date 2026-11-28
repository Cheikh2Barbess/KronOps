"""Listes fermees des actions (le moins de texte libre possible). Ne jamais retirer un code : des actions l'utilisent."""

from lots.reasons import OTHER

TYPES = {
    "maintenance": "Maintenance",
    "qualite": "Qualité",
    "production": "Production",
    "approvisionnement": "Approvisionnement",
}

# Objet de l'action : (type auquel il appartient, libelle). None = valable pour tous les types.
SUBJECTS = {
    "venir_au_poste": (None, "Venir au poste (appel de l'opérateur)"),
    "reparer_equipement": ("maintenance", "Réparer l'équipement"),
    "verifier_equipement": ("maintenance", "Vérifier ou régler l'équipement"),
    "remplacer_piece": ("maintenance", "Remplacer une pièce"),
    "planifier_revision": ("maintenance", "Planifier une révision"),
    "recontroler_lot": ("qualite", "Recontrôler le lot"),
    "decider_lot": ("qualite", "Décider du sort du lot (libérer, retrier, détruire)"),
    "analyser_cause": ("qualite", "Analyser la cause"),
    "rattraper_retard": ("production", "Rattraper le retard (heures en plus, autre équipement)"),
    "reorganiser_equipe": ("production", "Réorganiser l'équipe"),
    "former_personnel": ("production", "Former le personnel"),
    "commander_matiere": ("approvisionnement", "Commander ou relancer la matière"),
    "commander_emballage": ("approvisionnement", "Commander des emballages"),
    "commander_combustible": ("approvisionnement", "Commander du gaz ou du combustible"),
    OTHER: (None, "Autre (préciser)"),
}

PRIORITIES = {"haute": "Haute", "normale": "Normale"}

ORIGINS = {"saisie": "Saisie", "appel_poste": "Appel depuis le poste", "alerte": "Depuis une alerte"}

RESULTS = {
    "resolu": "Résolu",
    "partiel": "Résolu en partie",
    "non_resolu": "Non résolu, une autre action est nécessaire",
}

CANCEL = {
    "doublon": "Action en double",
    "plus_necessaire": "Plus nécessaire",
    "erreur_saisie": "Erreur de saisie",
    OTHER: "Autre (préciser)",
}


def subject_label(code, comment=""):
    if code == OTHER:
        return comment
    label = SUBJECTS.get(code, (None, code))[1]
    return f"{label} : {comment}" if comment else label
