from django.apps import AppConfig


class TenantsConfig(AppConfig):
    name = "tenants"
    verbose_name = "Entreprises et utilisateurs"

    def ready(self):
        from django.contrib.auth.models import update_last_login
        from django.contrib.auth.signals import user_logged_in

        from tenants.auth import record_last_login

        # La version de Django ecrirait la date de connexion sans contexte : la RLS la refuserait.
        user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")
        user_logged_in.connect(record_last_login, dispatch_uid="tenants_record_last_login")
