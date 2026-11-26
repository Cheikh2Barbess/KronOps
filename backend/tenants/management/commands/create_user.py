import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.tenancy import tenant_context
from tenants.models import User
from tenants.selectors import find_user_by_username, username_taken
from tenants.services import create_user


class Command(BaseCommand):
    help = "Ajoute un utilisateur (avec son role) dans l'entreprise d'un administrateur."

    def add_arguments(self, parser):
        parser.add_argument("--admin", required=True, help="Identifiant d'un administrateur de l'entreprise")
        parser.add_argument("--username", required=True, help="Identifiant de connexion du nouvel utilisateur")
        parser.add_argument("--role", required=True, choices=User.Role.values)
        parser.add_argument("--password", help="Deconseille (reste dans l'historique). Sinon demande au clavier.")

    def handle(self, *args, admin, username, role, password=None, **options):
        admin_user = find_user_by_username(admin)
        if admin_user is None or admin_user.role != User.Role.ADMIN or admin_user.tenant_id is None:
            raise CommandError(f"Aucun administrateur « {admin} ».")
        if username_taken(username):
            raise CommandError(f"L'identifiant {username} existe deja.")
        if not password:
            password = getpass.getpass(f"Mot de passe de {username} : ")
            if password != getpass.getpass("Confirmer : "):
                raise CommandError("Les deux mots de passe sont differents.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        with tenant_context(admin_user.tenant_id):
            user = create_user(tenant_id=admin_user.tenant_id, user=admin_user, username=username, password=password,
                               role=role)
        self.stdout.write(self.style.SUCCESS(f"Utilisateur {user.username} cree, role {user.get_role_display()}."))
