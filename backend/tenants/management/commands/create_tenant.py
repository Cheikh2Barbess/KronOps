import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.management.checks import ensure_database_migrated

from tenants.selectors import username_taken
from tenants.services import create_tenant_with_admin


class Command(BaseCommand):
    help = "Cree une entreprise cliente et son premier administrateur."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Nom de l'entreprise")
        parser.add_argument("--admin", required=True, help="Identifiant de connexion de l'administrateur")
        parser.add_argument("--email", default="")
        parser.add_argument("--password", help="Deconseille (reste dans l'historique). Sinon demande au clavier.")

    def handle(self, *args, name, admin, email, password=None, **options):
        ensure_database_migrated()
        if username_taken(admin):
            raise CommandError(f"L'identifiant {admin} existe deja.")
        if not password:
            password = getpass.getpass("Mot de passe de l'administrateur : ")
            if password != getpass.getpass("Confirmer : "):
                raise CommandError("Les deux mots de passe sont differents.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        tenant, user = create_tenant_with_admin(tenant_name=name, username=admin, password=password, email=email)
        self.stdout.write(self.style.SUCCESS(f"Entreprise « {tenant.name} » creee. Administrateur : {user.username}"))
