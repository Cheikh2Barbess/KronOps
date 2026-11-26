"""Authentification compatible avec la Row-Level Security de tenants_user.

Au debut d'une requete, l'entreprise n'est pas connue : la RLS cache tous les comptes.
- Connexion : TenantUserManager.get_by_natural_key passe par auth_user_by_username.
- Session : get_user ci-dessous passe par auth_user_by_id.
- Date de derniere connexion : ecrite dans le contexte du compte (record_last_login).
"""

from django.contrib.auth.backends import ModelBackend
from django.utils import timezone

from core.tenancy import account_context
from tenants.models import User


class TenantUserBackend(ModelBackend):
    def get_user(self, user_id):
        found = list(User.objects.raw("SELECT * FROM auth_user_by_id(%s)", [str(user_id)]))
        if not found:
            return None
        user = found[0]
        return user if self.user_can_authenticate(user) else None


def record_last_login(sender, user, **kwargs):
    """Remplace django.contrib.auth.models.update_last_login (qui ecrirait hors contexte)."""
    user.last_login = timezone.now()
    with account_context(user):
        user.save(update_fields=["last_login"])
