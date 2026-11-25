"""Filet de securite : toute table qui porte tenant_id doit avoir la RLS activee ET forcee.

Si ce test echoue apres l'ajout d'un modele, ajoute enable_rls("<table>") dans sa migration.
"""

from django.apps import apps
from django.db import connection

# Tables qui portent tenant_id mais sans RLS, par decision documentee.
EXCEPTIONS = {
    "tenants_user": "La connexion doit trouver l'utilisateur avant de connaitre son entreprise. "
    "Filtre obligatoire dans tenants/selectors.py.",
}


def tables_with_tenant_column():
    tables = set()
    for model in apps.get_models():
        field_names = {f.attname for f in model._meta.concrete_fields}
        if "tenant_id" in field_names:
            tables.add(model._meta.db_table)
    return tables


def test_every_tenant_table_has_forced_rls():
    tables = tables_with_tenant_column() - set(EXCEPTIONS)
    assert tables, "aucune table metier detectee, le test est mal configure"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = ANY(%s)",
            [list(tables)],
        )
        state = {name: (enabled, forced) for name, enabled, forced in cursor.fetchall()}
    missing = sorted(t for t in tables if state.get(t) != (True, True))
    assert not missing, f"RLS absente ou non forcee sur : {missing}"


def test_app_role_cannot_bypass_rls():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False, False)
