"""Filet de securite : toute table qui porte tenant_id doit avoir la RLS activee ET forcee.

Si ce test echoue apres l'ajout d'un modele, ajoute enable_rls("<table>") dans sa migration.
"""

from django.apps import apps
from django.db import connection

# Tables qui portent tenant_id mais sans RLS, par decision documentee du proprietaire.
# Vide depuis la migration tenants/0003 (tenants_user est protegee). Ne rien ajouter ici sans
# decision ecrite.
EXCEPTIONS = {}


def tables_with_tenant_column():
    """Vu par Django (modeles) ET par la base (colonnes reelles), pour ne rater aucune table,
    meme creee a la main dans une migration RunSQL."""
    tables = set()
    for model in apps.get_models():
        field_names = {f.attname for f in model._meta.concrete_fields}
        if "tenant_id" in field_names:
            tables.add(model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t USING (table_schema, table_name) "
            "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE'"
        )
        tables.update(name for (name,) in cursor.fetchall())
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


def test_users_table_is_protected():
    assert "tenants_user" in tables_with_tenant_column()
    assert "tenants_user" not in EXCEPTIONS


def test_app_role_cannot_bypass_rls():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False, False)
