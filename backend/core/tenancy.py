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
def _transaction_setting(name, value):
    """Ouvre une transaction, pose un reglage local, puis remet la valeur precedente a la sortie.

    Si ce bloc est imbrique dans une transaction plus large, le reglage survivrait a la sortie :
    on remet donc la valeur precedente. (En cas d'erreur, le retour arriere du point de
    sauvegarde restaure deja la valeur.)
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting(%s, true)", [name])
            previous = cursor.fetchone()[0] or ""
            cursor.execute("SELECT set_config(%s, %s, true)", [name, str(value)])
        yield
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config(%s, %s, true)", [name, previous])


@contextmanager
def tenant_context(tenant_id):
    """Pour les commandes, scripts et tests : ouvre une transaction et pose le tenant.

    Exemple :
        with tenant_context(tenant.id):
            Site.objects.create(tenant_id=tenant.id, name="Usine")
    """
    if tenant_id is None:
        raise TenantContextError("tenant_id manquant")
    token = current_tenant_id.set(str(tenant_id))
    try:
        with _transaction_setting("app.tenant_id", tenant_id):
            yield
    finally:
        current_tenant_id.reset(token)


@contextmanager
def platform_user_context(user_id):
    """Compte de l'equipe plateforme (sans entreprise) : rend visible SA PROPRE ligne
    utilisateur, et rien d'autre (politique platform_self de tenants_user).

    Sert a la connexion a l'admin Django (date de derniere connexion, mot de passe).
    """
    if user_id is None:
        raise TenantContextError("user_id manquant")
    with _transaction_setting("app.user_id", user_id):
        yield


def account_context(user):
    """Contexte qui permet de modifier la ligne de `user` lui-meme : son entreprise, ou sa
    propre ligne pour un compte plateforme."""
    if user.tenant_id is not None:
        return tenant_context(user.tenant_id)
    return platform_user_context(user.pk)
