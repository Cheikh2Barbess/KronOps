from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Etat du service. Public, ne revele aucune donnee client."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: dict, 503: dict})
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            database = "ok"
        except Exception:  # noqa: BLE001 - on veut un statut, pas une trace
            database = "erreur"
        status_code = 200 if database == "ok" else 503
        return Response({"status": "ok" if status_code == 200 else "degrade", "database": database}, status=status_code)
