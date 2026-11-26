from rest_framework.views import APIView

from core.tenancy import current_user_id, set_db_tenant


class TenantAPIView(APIView):
    """Classe de base de TOUTES les vues de l'API metier.

    Apres authentification, pose le tenant de l'utilisateur dans la transaction
    (ATOMIC_REQUESTS = True). La base filtre ensuite elle-meme les lignes.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentifie et verifie les permissions
        set_db_tenant(request.user.tenant_id)
        current_user_id.set(str(request.user.pk))
