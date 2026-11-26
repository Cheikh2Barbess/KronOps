from tenants.models import Site, User


def users_of_tenant(*, tenant_id):
    # La table User n'a pas de RLS : ce filtre est OBLIGATOIRE.
    return User.objects.filter(tenant_id=tenant_id).order_by("username")


def list_sites():
    # Pas de filtre tenant ici : la RLS de PostgreSQL le fait.
    return Site.objects.order_by("name")
