"""Outils de migration pour la Row-Level Security et les tables en insertion seule.

Utilisation dans une migration :

    from core.rls import enable_rls, make_append_only

    operations = [
        ...,  # CreateModel
        enable_rls("monapp_matable"),
    ]
"""

from django.conf import settings
from django.db import migrations

# NULLIF : apres un premier set_config dans la session, current_setting renvoie ''
# (et non NULL) hors transaction. ''::uuid planterait. NULLIF rend NULL, donc 0 ligne.
TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def enable_rls(table):
    return migrations.RunSQL(
        sql=f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = {TENANT_EXPR})
              WITH CHECK (tenant_id = {TENANT_EXPR});
        """,
        reverse_sql=f"""
            DROP POLICY IF EXISTS tenant_isolation ON {table};
            ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
            ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
        """,
    )


def make_append_only(table):
    """Interdit UPDATE, DELETE et TRUNCATE : trigger (pour tous les roles) + REVOKE (role applicatif)."""
    role = settings.DB_APP_ROLE
    return migrations.RunSQL(
        sql=f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
              FOR EACH ROW EXECUTE FUNCTION forbid_change();
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
              FOR EACH STATEMENT EXECUTE FUNCTION forbid_change();
            REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {role};
        """,
        reverse_sql=f"""
            DROP TRIGGER IF EXISTS {table}_append_only ON {table};
            DROP TRIGGER IF EXISTS {table}_no_truncate ON {table};
            GRANT UPDATE, DELETE ON {table} TO {role};
        """,
    )
