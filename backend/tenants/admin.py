from django.contrib import admin

from tenants.models import Tenant

# Seules les tables SANS RLS sont dans l'admin Django : l'admin ne pose pas de contexte
# tenant, donc les tables protegees y apparaitraient vides. C'est voulu.
# Les utilisateurs sont proteges par la RLS depuis la migration tenants/0003 : ils se gerent
# par l'ecran Utilisateurs (Admin de l'entreprise) et les commandes create_tenant / create_user.


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "plan", "is_active", "created_at"]
