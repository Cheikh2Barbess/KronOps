"""Lecture et validation des fichiers CSV du referentiel (US-02).

Un fichier est valide EN ENTIER ou refuse EN ENTIER : on collecte toutes les erreurs, ligne par ligne,
avant d'ecrire quoi que ce soit. La ligne 1 est l'en-tete.
"""

import csv
import io

from rest_framework.exceptions import ValidationError

from catalog import selectors, services
from catalog.api.serializers import ArticleSerializer, PartnerSerializer

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000


class CsvFileError(Exception):
    def __init__(self, errors):
        super().__init__("fichier invalide")
        self.errors = errors


def _line_error(line, messages):
    return {"line": line, "messages": messages}


# Nom de colonne du fichier pour chaque champ, pour des messages lisibles par l'utilisateur.
COLUMN_OF = {
    "code": "code", "name": "nom", "article_type": "type", "base_unit": "unite",
    "shelf_life_days": "duree_vie_jours", "storage": "conservation", "allergens": "allergènes",
    "address": "adresse", "contact_name": "contact", "phone": "telephone", "email": "email",
}


def _flatten(detail):
    """Transforme les erreurs DRF {champ: [msg]} en liste de phrases."""
    if isinstance(detail, dict):
        out = []
        for field, msgs in detail.items():
            for msg in _flatten(msgs):
                out.append(msg if field == "non_field_errors" else f"{COLUMN_OF.get(field, field)} : {msg}")
        return out
    if isinstance(detail, list):
        return [m for item in detail for m in _flatten(item)]
    return [str(detail)]


def read_rows(uploaded_file):
    """Renvoie (colonnes, [(numero_de_ligne, {colonne: valeur})])."""
    raw = uploaded_file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CsvFileError([_line_error(0, ["Fichier trop gros (2 Mo maximum)."])])
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")  # export Excel francais sous Windows
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise CsvFileError([_line_error(1, ["Fichier vide ou sans ligne d'en-tête."])])
    first = lines[0]
    delimiter = max([";", ",", "\t"], key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [h.strip().lower() for h in next(reader)]
    rows = []
    for number, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue  # ligne vide ignoree
        if len(rows) >= MAX_ROWS:
            raise CsvFileError([_line_error(number, [f"Trop de lignes ({MAX_ROWS} maximum par fichier)."])])
        if len(values) != len(header):
            rows.append((number, None))
            continue
        rows.append((number, {h: v.strip() for h, v in zip(header, values)}))
    if not rows:
        raise CsvFileError([_line_error(2, ["Aucune ligne de données."])])
    return header, rows


def _check_header(header, required, optional):
    missing = [c for c in required if c not in header]
    unknown = [c for c in header if c not in required and c not in optional]
    messages = []
    if missing:
        messages.append(f"Colonnes manquantes : {', '.join(missing)}.")
    if unknown:
        messages.append(f"Colonnes inconnues : {', '.join(unknown)}.")
    if len(set(header)) != len(header):
        messages.append("Une colonne apparaît deux fois.")
    if messages:
        raise CsvFileError([_line_error(1, messages)])


# Articles -----------------------------------------------------------------

ARTICLE_REQUIRED = ["code", "nom", "type", "unite"]
ARTICLE_OPTIONAL = ["duree_vie_jours", "conservation"]


def parse_articles(uploaded_file):
    codes = selectors.allergen_codes()
    header, rows = read_rows(uploaded_file)
    _check_header(header, ARTICLE_REQUIRED, ARTICLE_OPTIONAL + codes)
    errors, valid, seen = [], [], {}
    existing = selectors.existing_article_codes([r["code"] for _, r in rows if r])
    for line, row in rows:
        if row is None:
            errors.append(_line_error(line, ["Nombre de colonnes différent de l'en-tête."]))
            continue
        messages = []
        data = {
            "code": row["code"], "name": row["nom"], "article_type": row["type"].lower(),
            "base_unit": row["unite"].lower(), "storage": row.get("conservation", "").lower(),
            "shelf_life_days": row.get("duree_vie_jours") or None,
        }
        serializer = ArticleSerializer(data=data)
        if not serializer.is_valid():
            messages += _flatten(serializer.errors)
        given = {c: row[c].lower().replace(" ", "_") for c in codes if row.get(c)}
        allergens = given or None
        try:
            allergens = services.check_allergen_declaration(article_type=data["article_type"], allergens=allergens)
        except ValidationError as exc:
            messages += _flatten(exc.detail)
        if data["code"] in existing:
            messages.append(f"Le code {data['code']} existe déjà dans KronOps.")
        if data["code"] in seen:
            messages.append(f"Code {data['code']} en double dans le fichier (déjà ligne {seen[data['code']]}).")
        seen.setdefault(data["code"], line)
        if messages:
            errors.append(_line_error(line, messages))
        else:
            valid.append({**serializer.validated_data, "allergens": allergens})
    if errors:
        raise CsvFileError(errors)
    return valid


# Partenaires --------------------------------------------------------------

PARTNER_REQUIRED = ["nom", "fournisseur", "client", "adresse"]
PARTNER_OPTIONAL = ["contact", "telephone", "email"]
YES = {"oui", "o", "x", "1", "vrai", "yes"}
NO = {"non", "n", "", "0", "faux", "no"}


def _yes_no(value, column, messages):
    v = value.strip().lower()
    if v in YES:
        return True
    if v not in NO:
        messages.append(f"{column} : répondre oui ou non (valeur « {value} »).")
    return False


def parse_partners(uploaded_file):
    header, rows = read_rows(uploaded_file)
    _check_header(header, PARTNER_REQUIRED, PARTNER_OPTIONAL)
    errors, valid, seen = [], [], {}
    existing = selectors.existing_partner_names([r["nom"] for _, r in rows if r])
    for line, row in rows:
        if row is None:
            errors.append(_line_error(line, ["Nombre de colonnes différent de l'en-tête."]))
            continue
        messages = []
        data = {
            "name": row["nom"], "address": row["adresse"],
            "is_supplier": _yes_no(row["fournisseur"], "fournisseur", messages),
            "is_customer": _yes_no(row["client"], "client", messages),
            "contact_name": row.get("contact", ""), "phone": row.get("telephone", ""), "email": row.get("email", ""),
        }
        serializer = PartnerSerializer(data=data)
        if not serializer.is_valid():
            messages += _flatten(serializer.errors)
        if not (data["is_supplier"] or data["is_customer"]):
            messages.append("Un partenaire est fournisseur, client, ou les deux.")
        key = data["name"].lower()
        if key in existing:
            messages.append(f"Le partenaire « {data['name']} » existe déjà dans KronOps.")
        if key in seen:
            messages.append(f"Partenaire en double dans le fichier (déjà ligne {seen[key]}).")
        seen.setdefault(key, line)
        if messages:
            errors.append(_line_error(line, messages))
        else:
            valid.append(serializer.validated_data)
    if errors:
        raise CsvFileError(errors)
    return valid
