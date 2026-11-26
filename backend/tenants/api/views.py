from django.contrib.auth import authenticate, login, logout
from django.http import Http404
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import TenantAPIView
from tenants import selectors, services
from tenants.api.serializers import LoginSerializer, MeSerializer, SiteSerializer
from tenants.permissions import ReferentialPermission


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
