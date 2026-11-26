"""Postes (liste fermee). Regle du proprietaire, 26/11/2026 : le moins de texte libre possible.
« Autre » exige une precision. A rendre configurable par entreprise plus tard."""

OTHER = "autre"

JOB_TITLES = {
    "directeur": "Directeur général",
    "responsable_production": "Responsable production",
    "chef_equipe": "Chef d'équipe",
    "operateur_production": "Opérateur de production",
    "responsable_qualite": "Responsable qualité",
    "technicien_qualite": "Technicien qualité",
    "magasinier": "Magasinier",
    "receptionnaire": "Réceptionnaire",
    "responsable_logistique": "Responsable logistique",
    "responsable_maintenance": "Responsable maintenance",
    "technicien_maintenance": "Technicien de maintenance",
    "comptable": "Comptable",
    "commercial": "Commercial",
    OTHER: "Autre (préciser)",
}


def label(code, other=""):
    if code == OTHER:
        return other
    return JOB_TITLES.get(code, "")


def as_options():
    return [{"code": code, "label": text} for code, text in JOB_TITLES.items()]
