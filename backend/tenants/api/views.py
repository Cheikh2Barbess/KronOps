from django.contrib.auth import authenticate, login, logout
from django.http import Http404
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import TenantAPIView
from tenants import selectors, services
from tenants import jobs
from tenants.api.serializers import (
    LoginSerializer, MeSerializer, PersonSerializer, SiteSerializer, UserCardSerializer, UserWriteSerializer,
)
from tenants.models import User
from tenants.permissions import ReferentialPermission, UserCardPermission, UserManagePermission


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Pose le cookie csrftoken. Le front l'appelle une fois avant de se connecter."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """Connexion. Protection CSRF imposee meme pour un visiteur non connecte
    (DRF ne la verifie d'habitude que pour les utilisateurs deja connectes)."""

    permission_classes = [AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: MeSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        # Message identique dans tous les cas : ne pas reveler si le compte existe.
        if user is None or user.tenant_id is None or not user.tenant.is_active:
            return Response({"detail": "Identifiants invalides."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(TenantAPIView):
    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class SiteListView(TenantAPIView):
    permission_classes = [IsAuthenticated, ReferentialPermission]

    @extend_schema(responses={200: SiteSerializer(many=True)})
    def get(self, request):
        return Response(SiteSerializer(selectors.list_sites(), many=True).data)

    @extend_schema(request=SiteSerializer, responses={201: SiteSerializer})
    def post(self, request):
        serializer = SiteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        site = services.create_site(tenant_id=request.user.tenant_id, user=request.user, **serializer.validated_data)
        return Response(SiteSerializer(site).data, status=status.HTTP_201_CREATED)


class SiteDetailView(TenantAPIView):
    permission_classes = [IsAuthenticated, ReferentialPermission]

    @extend_schema(responses={200: SiteSerializer})
    def get(self, request, pk):
        site = selectors.list_sites().filter(pk=pk).first()
        if site is None:  # inexistant OU appartenant a un autre client : meme reponse 404
            raise Http404
        return Response(SiteSerializer(site).data)


def _manager(request, data):
    """Le superieur est cherche dans l'entreprise de l'admin seulement (table sans RLS)."""
    if "manager" not in data:
        return data
    manager_id = data["manager"]
    if manager_id is None:
        return data
    manager = selectors.users_of_tenant(tenant_id=request.user.tenant_id).filter(pk=manager_id).first()
    if manager is None:
        raise ValidationError({"manager": ["Supérieur introuvable."]})
    return {**data, "manager": manager}


class UserListView(TenantAPIView):
    """Ecran Utilisateurs (Admin) : liste complete et creation."""

    permission_classes = [IsAuthenticated, UserManagePermission]

    @extend_schema(responses={200: UserCardSerializer(many=True)})
    def get(self, request):
        users = selectors.users_of_tenant(tenant_id=request.user.tenant_id).select_related("manager")
        return Response(UserCardSerializer(users, many=True).data)

    @extend_schema(request=UserWriteSerializer, responses={201: UserCardSerializer})
    def post(self, request):
        serializer = UserWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _manager(request, serializer.validated_data)
        missing = [f for f in ("username", "password", "role") if not data.get(f)]
        if missing:
                raise ValidationError({f: ["Ce champ est obligatoire."] for f in missing})
        data.pop("is_active", None)
        user = services.create_user(tenant_id=request.user.tenant_id, user=request.user, **data)
        return Response(UserCardSerializer(user).data, status=status.HTTP_201_CREATED)


class UserOptionsView(TenantAPIView):
    """Listes du formulaire : postes et roles. Ce ne sont pas des donnees personnelles : lisibles par les
    responsables, pour traduire les codes du journal."""

    permission_classes = [IsAuthenticated, UserCardPermission]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({
            "job_titles": jobs.as_options(),
            "roles": [{"code": code, "label": label} for code, label in User.Role.choices],
        })


class UserDirectoryView(TenantAPIView):
    """Annuaire court (nom complet, poste) pour afficher les personnes partout. Responsables seulement."""

    permission_classes = [IsAuthenticated, UserCardPermission]

    @extend_schema(responses={200: PersonSerializer(many=True)})
    def get(self, request):
        return Response(PersonSerializer(selectors.users_of_tenant(tenant_id=request.user.tenant_id), many=True).data)


class UserDetailView(TenantAPIView):
    """Fiche d'une personne : lecture par les responsables, modification par l'Admin."""

    permission_classes = [IsAuthenticated, UserCardPermission]

    @extend_schema(responses={200: UserCardSerializer})
    def get(self, request, pk):
        user = selectors.user_of_tenant_or_404(tenant_id=request.user.tenant_id, user_id=pk)
        return Response(UserCardSerializer(user).data)

    @extend_schema(request=UserWriteSerializer, responses={200: UserCardSerializer})
    def patch(self, request, pk):
        target = selectors.user_of_tenant_or_404(tenant_id=request.user.tenant_id, user_id=pk)
        serializer = UserWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = _manager(request, serializer.validated_data)
        data.pop("username", None)  # l'identifiant ne change pas : il est cite dans tout le journal
        user = services.update_user(tenant_id=request.user.tenant_id, user=request.user, target=target, **data)
        return Response(UserCardSerializer(user).data)
