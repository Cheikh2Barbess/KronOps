"""Row-Level Security sur la table des utilisateurs (point d'audit L-037).

Avant : tenants_user etait la seule table metier sans RLS, filtree seulement dans le code.
Apres : la base cache les comptes des autres entreprises, comme pour toutes les autres tables.

Trois chemins d'acces, et seulement trois :
1. tenant_isolation (standard) : les comptes de l'entreprise posee dans app.tenant_id.
2. platform_self : un compte plateforme (sans entreprise, equipe Tracalys) voit et modifie
   SA PROPRE ligne quand app.user_id vaut son id (connexion a l'admin Django).
3. Fonctions auth_* (SECURITY DEFINER, executees avec les droits du role proprietaire) : elles
   retrouvent UN compte par identifiant exact ou par id. C'est ce qu'il faut a la connexion
   et a la session, qui ne connaissent pas encore l'entreprise. Le role proprietaire est
   soumis a FORCE ROW LEVEL SECURITY : la politique owner_access lui ouvre cette table (et
   seulement celle-ci), pour que ces fonctions marchent. Le role applicatif n'en profite pas.

Migration reversible, sans perte de donnees (aucune colonne ni ligne modifiee).
"""

from django.conf import settings
from django.db import migrations

import tenants.models
from core.rls import USER_EXPR, enable_rls

APP = settings.DB_APP_ROLE

FUNCTIONS_SQL = f"""
CREATE POLICY platform_self ON tenants_user
  USING (tenant_id IS NULL AND id = {USER_EXPR})
  WITH CHECK (tenant_id IS NULL AND id = {USER_EXPR});

-- CURRENT_USER = le role qui joue les migrations (proprietaire des tables).
CREATE POLICY owner_access ON tenants_user TO CURRENT_USER USING (true) WITH CHECK (true);

CREATE FUNCTION auth_user_by_username(p_username text) RETURNS SETOF tenants_user
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
  AS $$ SELECT * FROM public.tenants_user WHERE username = p_username $$;

CREATE FUNCTION auth_user_by_id(p_id uuid) RETURNS SETOF tenants_user
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
  AS $$ SELECT * FROM public.tenants_user WHERE id = p_id $$;

-- Les identifiants sont uniques sur toute la plateforme : il faut savoir si un identifiant
-- est pris ailleurs, sans voir le compte. Renvoie seulement vrai ou faux.
CREATE FUNCTION auth_username_taken(p_username text) RETURNS boolean
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
  AS $$ SELECT EXISTS (SELECT 1 FROM public.tenants_user WHERE upper(username) = upper(p_username)) $$;

REVOKE ALL ON FUNCTION auth_user_by_username(text), auth_user_by_id(uuid), auth_username_taken(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_user_by_username(text), auth_user_by_id(uuid), auth_username_taken(text) TO {APP};
"""

FUNCTIONS_REVERSE_SQL = """
DROP FUNCTION IF EXISTS auth_username_taken(text);
DROP FUNCTION IF EXISTS auth_user_by_id(uuid);
DROP FUNCTION IF EXISTS auth_user_by_username(text);
DROP POLICY IF EXISTS owner_access ON tenants_user;
DROP POLICY IF EXISTS platform_self ON tenants_user;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0002_user_card"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="user",
            managers=[("objects", tenants.models.TenantUserManager())],
        ),
        enable_rls("tenants_user"),
        migrations.RunSQL(sql=FUNCTIONS_SQL, reverse_sql=FUNCTIONS_REVERSE_SQL),
    ]
