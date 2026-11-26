from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from core.tenancy import current_user_id, set_db_tenant


class TenantAPIView(APIView):
    """Classe de base de TOUTES les vues de l'API metier.

    Apres authentification, pose le tenant de l'utilisateur dans la transaction
    (ATOMIC_REQUESTS = True). La base filtre ensuite elle-meme les lignes.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentifie et verifie les permissions
        if request.user.tenant_id is None:  # compte plateforme connecte a l'admin Django
            raise PermissionDenied("Ce compte n'appartient à aucune entreprise.")
        set_db_tenant(request.user.tenant_id)
        current_user_id.set(str(request.user.pk))
