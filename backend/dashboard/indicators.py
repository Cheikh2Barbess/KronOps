"""Catalogue des seuils du tableau de bord et regle des couleurs.

Chaque seuil a une valeur PAR DEFAUT (proposee par Tracalys, a ajuster par le client) et peut etre
change par l'Admin de l'entreprise. Un indicateur sans seuil reste neutre (« info ») : on ne colore
jamais une valeur sans regle connue.

Sens :
- HIGHER (plus c'est haut, mieux c'est) : vert si valeur >= seuil vert, rouge si valeur < seuil rouge.
- LOWER (plus c'est bas, mieux c'est) : vert si valeur <= seuil vert, rouge si valeur > seuil rouge.
Entre les deux : jaune.
"""

from decimal import Decimal

HIGHER = "higher"
LOWER = "lower"
DIRECTION_LABELS = {HIGHER: "Plus c'est haut, mieux c'est", LOWER: "Plus c'est bas, mieux c'est"}

OK, WARN, BAD, INFO = "ok", "warn", "bad", "info"
STATUS_LABELS = {OK: "OK", WARN: "À surveiller", BAD: "Non OK", INFO: "Information"}

# Valeurs par defaut : choix de depart de Tracalys, sans norme officielle derriere. A regler avec le client.
THRESHOLDS = {
    "qc_conformity_pct": {
        "label": "Contrôles qualité conformes", "unit": "%", "direction": HIGHER, "green": "95", "red": "85",
        "help": "Part des contrôles qualité conformes sur la période.",
    },
    "yield_in_range_pct": {
        "label": "Déclarations dans la fourchette de rendement", "unit": "%", "direction": HIGHER,
        "green": "90", "red": "75",
        "help": "Part des déclarations d'étape (avec fourchette dans l'article) dont le rendement est dans la fourchette.",
    },
    "reception_conform_pct": {
        "label": "Réceptions conformes au contrôle visuel", "unit": "%", "direction": HIGHER,
        "green": "98", "red": "95",
        "help": "Part des livraisons reçues avec un contrôle visuel conforme.",
    },
    "late_entries_pct": {
        "label": "Saisies tardives", "unit": "%", "direction": LOWER, "green": "5", "red": "15",
        "help": "Part des réceptions et déclarations saisies plus de 2 heures après le geste.",
    },
    "blocked_lots": {
        "label": "Lots bloqués en stock", "unit": "lots", "direction": LOWER, "green": "0", "red": "3",
        "help": "Nombre de lots bloqués qui ont encore du stock.",
    },
    "pending_approval_hours": {
        "label": "Âge de la plus ancienne demande de validation", "unit": "h", "direction": LOWER,
        "green": "24", "red": "72",
        "help": "Heures depuis la plus ancienne demande de double validation encore en attente.",
    },
    "step_wait_hours": {
        "label": "Attente avant une étape", "unit": "h", "direction": LOWER, "green": "24", "red": "48",
        "help": "Heures entre la sortie d'un lot (réception ou étape précédente) et le début de l'étape qui le prend.",
    },
    "expiry_days": {
        "label": "Jours restants avant la DLC ou la DDM", "unit": "j", "direction": HIGHER, "green": "30", "red": "0",
        "help": "Un lot en stock passe en jaune sous le seuil vert, en rouge quand sa date est dépassée.",
    },
}


def defaults(code):
    item = THRESHOLDS[code]
    return Decimal(item["green"]), Decimal(item["red"])


def status_for(value, *, direction, green, red):
    """Couleur d'une valeur selon son seuil. Sans valeur : neutre."""
    if value is None:
        return INFO
    value = Decimal(str(value))
    if direction == HIGHER:
        if value >= green:
            return OK
        return BAD if value < red else WARN
    if value <= green:
        return OK
    return BAD if value > red else WARN


def worst(statuses):
    """Le pire des etats (rouge avant jaune avant vert). Neutre si aucun."""
    for s in (BAD, WARN, OK):
        if s in statuses:
            return s
    return INFO
