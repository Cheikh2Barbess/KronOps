from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from tenants.models import Tenant, User

# Seules les tables SANS RLS sont dans l'admin Django : l'admin ne pose pas de contexte
# tenant, donc les tables protegees y apparaitraient vides. C'est voulu.


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "plan", "is_active", "created_at"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "tenant", "role", "is_active"]
    list_filter = ["role", "tenant"]
    fieldsets = BaseUserAdmin.fieldsets + (("KronOps", {"fields": ("tenant", "role")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("KronOps", {"fields": ("tenant", "role")}),)
