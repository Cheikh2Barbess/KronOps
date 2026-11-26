from django.db import connection

from events.models import OutboxEvent


class OutsideTransactionError(RuntimeError):
    pass


def publish_event(*, tenant_id, event_type, payload):
    """Enregistre un evenement. Uniquement a l'interieur d'une transaction ouverte.

    Si l'action echoue et que la transaction est annulee, l'evenement disparait avec elle.
    """
    if not connection.in_atomic_block:
        raise OutsideTransactionError("publish_event doit etre appele dans une transaction")
    return OutboxEvent.objects.create(tenant_id=tenant_id, event_type=event_type, payload=payload)
