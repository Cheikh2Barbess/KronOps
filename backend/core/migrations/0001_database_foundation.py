"""Fondations de la base, jouees avant toute autre migration.

1. Droits par defaut : toute table creee par le role proprietaire (celui qui joue les
   migrations) est utilisable par le role applicatif, sans en etre proprietaire.
2. Fonction forbid_change(), utilisee par les tables en insertion seule.
"""

from django.conf import settings
from django.db import migrations

ROLE = settings.DB_APP_ROLE


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    run_before = [
        ("contenttypes", "0001_initial"),
        ("auth", "0001_initial"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"""
                GRANT USAGE ON SCHEMA public TO {ROLE};
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE};
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  GRANT USAGE, SELECT ON SEQUENCES TO {ROLE};
            """,
            reverse_sql=f"""
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE};
            """,
        ),
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION forbid_change() RETURNS trigger AS $$
                BEGIN
                  RAISE EXCEPTION 'Table en insertion seule : % interdit sur %', TG_OP, TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
                END;
                $$ LANGUAGE plpgsql;
            """,
            reverse_sql="DROP FUNCTION IF EXISTS forbid_change();",
        ),
    ]
