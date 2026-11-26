"""US-02 : import CSV. Un fichier invalide est refuse EN ENTIER, avec la liste des lignes en erreur."""

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from audit.models import AuditLog
from catalog.models import Article, Partner
from core.tenancy import tenant_context

ALLERGENS = (
    "gluten;crustaces;oeufs;poissons;arachides;soja;lait;fruits_a_coque;"
    "celeri;moutarde;sesame;sulfites;lupin;mollusques"
)
HEADER = "code;nom;type;unite;duree_vie_jours;conservation;" + ALLERGENS
NONE = ";".join(["absent"] * 14)
EMPTY = ";" * 13


def upload(client, url, text, encoding="utf-8"):
    file = SimpleUploadedFile("import.csv", text.encode(encoding), content_type="text/csv")
    return client.post(url, {"file": file}, format="multipart")


def test_valid_article_file_creates_everything(client_a, tenant_a):
    text = "\n".join(
        [
            HEADER,
            "MP-FAR;Farine de blé;matiere;kg;180;ambiant;contient;" + ";".join(["absent"] * 13),
            "MP-SUC;Sucre;matiere;kg;;ambiant;" + NONE,
            "EMB-01;Sachet 1 kg;emballage;unite;;;" + EMPTY,
        ]
    )
    response = upload(client_a, "/api/v1/articles/import/", text)
    assert response.status_code == 201, response.json()
    assert response.json() == {"created": 3}
    with tenant_context(tenant_a.id):
        assert Article.objects.count() == 3
        assert AuditLog.objects.filter(entity_type="catalog.article", action="import").count() == 3


def test_one_bad_line_rejects_the_whole_file(client_a, tenant_a):
    text = "\n".join(
        [
            HEADER,
            "MP-SUC;Sucre;matiere;kg;;ambiant;" + NONE,
            "MP-SEL;Sel;matiere;tonne;;ambiant;" + NONE,  # unite inconnue
            "MP-HUI;Huile;matiere;l;;ambiant;" + EMPTY,  # matiere sans declaration d'allergenes
            "MP-SUC;Sucre bis;matiere;kg;;ambiant;" + NONE,  # code en double dans le fichier
        ]
    )
    response = upload(client_a, "/api/v1/articles/import/", text)
    assert response.status_code == 400
    errors = response.json()["errors"]
    assert sorted(e["line"] for e in errors) == [3, 4, 5]
    with tenant_context(tenant_a.id):
        assert Article.objects.count() == 0


def test_code_already_in_database_is_an_error(client_a, all_absent):
    client_a.post(
        "/api/v1/articles/",
        {"code": "MP-SUC", "name": "Sucre", "article_type": "matiere", "base_unit": "kg", "allergens": all_absent},
        format="json",
    )
    response = upload(client_a, "/api/v1/articles/import/", HEADER + "\nMP-SUC;Sucre;matiere;kg;;ambiant;" + NONE)
    assert response.status_code == 400
    assert response.json()["errors"][0]["line"] == 2


def test_missing_column_is_refused(client_a):
    response = upload(client_a, "/api/v1/articles/import/", "code;nom\nMP-1;Sucre")
    assert response.status_code == 400
    assert response.json()["errors"][0]["line"] == 1


def test_excel_french_export_is_accepted(client_a):
    # Excel en francais enregistre souvent en Windows-1252 avec des accents.
    text = HEADER + "\nMP-CAF;Café vert;matiere;kg;;ambiant;" + NONE
    response = upload(client_a, "/api/v1/articles/import/", text, encoding="cp1252")
    assert response.status_code == 201, response.json()


def test_comma_separator_is_accepted(client_a):
    text = (HEADER + "\nMP-SUC;Sucre;matiere;kg;;ambiant;" + NONE).replace(";", ",")
    assert upload(client_a, "/api/v1/articles/import/", text).status_code == 201


def test_empty_file_is_refused(client_a):
    assert upload(client_a, "/api/v1/articles/import/", "").status_code == 400


def test_production_cannot_import(production_client):
    response = upload(production_client, "/api/v1/articles/import/", HEADER)
    assert response.status_code == 403


def test_import_partners(client_a, tenant_a):
    text = "\n".join(
        [
            "nom;fournisseur;client;adresse;contact;telephone;email",
            "Moulins CI;oui;non;Abidjan;M. Koné;0102030405;",
            "Supermarché Plateau;non;oui;Plateau, Abidjan;;;achats@example.com",
        ]
    )
    response = upload(client_a, "/api/v1/partners/import/", text)
    assert response.status_code == 201, response.json()
    with tenant_context(tenant_a.id):
        assert Partner.objects.count() == 2


def test_bad_partner_lines_reject_the_file(client_a, tenant_a):
    text = "\n".join(
        [
            "nom;fournisseur;client;adresse;contact;telephone;email",
            "Moulins CI;oui;non;;;;",  # adresse manquante
            "Sans role;non;non;Abidjan;;;",  # ni fournisseur ni client
            "Mauvais mail;oui;non;Abidjan;;;pas-un-mail",
        ]
    )
    response = upload(client_a, "/api/v1/partners/import/", text)
    assert response.status_code == 400
    assert [e["line"] for e in response.json()["errors"]] == [2, 3, 4]
    with tenant_context(tenant_a.id):
        assert Partner.objects.count() == 0


def test_imported_rows_land_in_own_tenant_only(client_a, client_b, tenant_b):
    upload(client_a, "/api/v1/articles/import/", HEADER + "\nMP-SUC;Sucre;matiere;kg;;ambiant;" + NONE)
    assert client_b.get("/api/v1/articles/").json() == []
    with tenant_context(tenant_b.id):
        assert Article.objects.count() == 0


MODELS_DIR = Path(__file__).resolve().parents[3] / "frontend" / "public" / "modeles"


@pytest.mark.skipif(not MODELS_DIR.exists(), reason="dossier frontend absent (lancement dans Docker)")
@pytest.mark.parametrize(
    "name,url", [("articles.csv", "/api/v1/articles/import/"), ("partenaires.csv", "/api/v1/partners/import/")]
)
def test_downloadable_templates_import_without_error(client_a, name, url):
    # Les modeles proposes au telechargement dans l'ecran doivent toujours etre acceptes.
    file = SimpleUploadedFile(name, (MODELS_DIR / name).read_bytes(), content_type="text/csv")
    response = client_a.post(url, {"file": file}, format="multipart")
    assert response.status_code == 201, response.json()
