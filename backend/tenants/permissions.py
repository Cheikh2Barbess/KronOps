"""Permissions par role. Reference : matrice des droits du PRD.

Le front masque les boutons, mais c'est ICI que la regle est appliquee.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from tenants.models import User

R = User.Role


def has_role(user, *roles):
    return bool(user and user.is_authenticated and user.tenant_id and user.role in roles)


class ReferentialPermission(BasePermission):
    """Referentiels (articles, sites, fournisseurs...) : ecriture Admin et Qualite, lecture Production et Lecture."""

    message = "Votre rôle ne permet pas cette action."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return has_role(request.user, R.ADMIN, R.QUALITE, R.PRODUCTION, R.LECTURE)
        return has_role(request.user, R.ADMIN, R.QUALITE)


class IsTenantAdmin(BasePermission):
    message = "Réservé à l'administrateur de l'entreprise."

    def has_permission(self, request, view):
        return has_role(request.user, R.ADMIN)
