from django.db import connection
from django.http import Http404

from tenants.models import Site, User


def users_of_tenant(*, tenant_id):
    # La RLS filtre deja par entreprise. Ce filtre explicite reste, par securite en profondeur.
    return User.objects.filter(tenant_id=tenant_id).order_by("username")


def user_of_tenant_or_404(*, tenant_id, user_id):
    user = users_of_tenant(tenant_id=tenant_id).select_related("manager").filter(pk=user_id).first()
    if user is None:  # inexistant OU d'une autre entreprise
        raise Http404
    return user


def list_sites():
    # Pas de filtre tenant ici : la RLS de PostgreSQL le fait.
    return Site.objects.order_by("name")


def find_user_by_username(username):
    """Compte par identifiant exact, quelle que soit l'entreprise. Pour la connexion et les
    commandes d'administration seulement (hors requete, sans contexte d'entreprise)."""
    try:
        return User.objects.get_by_natural_key(username)
    except User.DoesNotExist:
        return None


def username_taken(username):
    """Vrai si l'identifiant existe deja, dans n'importe quelle entreprise (insensible a la casse).
    Ne revele rien d'autre que oui ou non."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT auth_username_taken(%s)", [username])
        return cursor.fetchone()[0]
