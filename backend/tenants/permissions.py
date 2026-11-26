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


class AuditReadPermission(BasePermission):
    """Journal d'audit : lecture Admin et Qualite, aucune ecriture par l'API."""

    message = "Le journal d'audit est réservé aux rôles Admin et Qualité."

    def has_permission(self, request, view):
        # Les vues du journal n'ont que GET : toute ecriture repond 405.
        return has_role(request.user, R.ADMIN, R.QUALITE)


class LotPermission(BasePermission):
    """Lots : lecture pour tous les roles. Reception (ecriture) : Admin, Qualite, Production, Operateur."""

    message = "Votre rôle ne permet pas cette action."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return has_role(request.user, *R.values)
        return has_role(request.user, R.ADMIN, R.QUALITE, R.PRODUCTION, R.OPERATEUR)


class ReceptionPermission(BasePermission):
    """Ecran de reception : seulement les roles qui peuvent enregistrer une livraison."""

    message = "Votre rôle ne permet pas d'enregistrer une réception."

    def has_permission(self, request, view):
        return has_role(request.user, R.ADMIN, R.QUALITE, R.PRODUCTION, R.OPERATEUR)


class BlockLotPermission(BasePermission):
    message = "Seuls les rôles Admin, Qualité et Production peuvent bloquer un lot."

    def has_permission(self, request, view):
        return has_role(request.user, R.ADMIN, R.QUALITE, R.PRODUCTION)


class TraceabilityPermission(BasePermission):
    message = "La recherche amont/aval n'est pas ouverte à votre rôle."

    def has_permission(self, request, view):
        return has_role(request.user, R.ADMIN, R.QUALITE, R.PRODUCTION, R.LECTURE)


class ApprovalPermission(BasePermission):
    """Double validation (US-20) : ouverte a tous les roles sauf Lecture. Le detail (qui demande quoi,
    qui valide) est verifie par lots/services.py selon la matrice des droits du PRD."""

    message = "La double validation n'est pas ouverte à votre rôle."

    def has_permission(self, request, view):
        return has_role(request.user, R.ADMIN, R.QUALITE, R.PRODUCTION, R.OPERATEUR)


class UserManagePermission(BasePermission):
    """Gestion des utilisateurs (creer, modifier, desactiver) : Admin seulement."""

    message = "Seul l'administrateur de l'entreprise gère les utilisateurs."

    def has_permission(self, request, view):
        return has_role(request.user, R.ADMIN)


# « Responsables » (regle proposee le 26/11/2026) : Admin, Qualite, Production. Ni Operateur ni Lecture.
RESPONSABLES = (R.ADMIN, R.QUALITE, R.PRODUCTION)


class UserCardPermission(BasePermission):
    """Fiches des personnes (nom, poste, telephone, e-mail, superieur) : donnees personnelles, minimisation
    (loi ivoirienne 2013-450). Lecture par les responsables, modification par l'Admin."""

    message = "Les fiches des personnes sont réservées aux responsables."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return has_role(request.user, *RESPONSABLES)
        return has_role(request.user, R.ADMIN)
