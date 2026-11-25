from django.db import connection

from audit.models import AuditLog


def record_audit(*, tenant_id, user, action, entity, old_values=None, new_values=None):
    """Ecrit une ligne d'audit. A appeler dans la transaction de l'action metier."""
    if not connection.in_atomic_block:
        raise RuntimeError("record_audit doit etre appele dans une transaction")
    return AuditLog.objects.create(
        tenant_id=tenant_id,
        user=user if user is not None and user.is_authenticated else None,
        action=action,
        entity_type=entity._meta.label_lower,
        entity_id=entity.pk,
        old_values=old_values,
        new_values=new_values,
    )
