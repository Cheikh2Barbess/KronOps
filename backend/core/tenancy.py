"""Contexte client (tenant) pour la Row-Level Security PostgreSQL.

La base ne montre que les lignes dont tenant_id vaut le reglage app.tenant_id.
Ce reglage est pose avec set_config(..., true), donc valable uniquement pour la
transaction en cours. Il faut donc toujours etre dans une transaction.
"""

import contextvars
from contextlib import contextmanager

from django.db import connection, transaction

current_tenant_id = contextvars.ContextVar("current_tenant_id", default=None)
current_user_id = contextvars.ContextVar("current_user_id", default=None)


class TenantContextError(RuntimeError):
    pass


def set_db_tenant(tenant_id):
    """Pose le tenant pour la transaction en cours. Leve une erreur hors transaction."""
    if tenant_id is None:
        raise TenantContextError("tenant_id manquant")
    if not connection.in_atomic_block:
        raise TenantContextError(
            "set_db_tenant doit etre appele dans une transaction (sinon le reglage est perdu)"
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
    current_tenant_id.set(str(tenant_id))


@contextmanager
def tenant_context(tenant_id):
    """Pour les commandes, scripts et tests : ouvre une transaction et pose le tenant.

    Exemple :
        with tenant_context(tenant.id):
            Site.objects.create(tenant_id=tenant.id, name="Usine")
    """
    token = current_tenant_id.set(str(tenant_id))
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.tenant_id', true)")
                previous = cursor.fetchone()[0] or ""
            set_db_tenant(tenant_id)
            yield
            # Si ce bloc est imbrique dans une transaction plus large, le reglage survivrait
            # a la sortie : on remet la valeur precedente. (En cas d'erreur, le retour
            # arriere du point de sauvegarde restaure deja la valeur.)
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [previous])
    finally:
        current_tenant_id.reset(token)
