from django.http import Http404

from tenants.models import Site, User


def users_of_tenant(*, tenant_id):
    # La table User n'a pas de RLS : ce filtre est OBLIGATOIRE.
    return User.objects.filter(tenant_id=tenant_id).order_by("username")


def user_of_tenant_or_404(*, tenant_id, user_id):
    user = users_of_tenant(tenant_id=tenant_id).select_related("manager").filter(pk=user_id).first()
    if user is None:  # inexistant OU d'une autre entreprise
        raise Http404
    return user


def list_sites():
    # Pas de filtre tenant ici : la RLS de PostgreSQL le fait.
    return Site.objects.order_by("name")
