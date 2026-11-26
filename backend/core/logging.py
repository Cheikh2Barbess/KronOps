"""Ajoute tenant_id et user_id a chaque ligne de log."""

import logging

from core.tenancy import current_tenant_id, current_user_id


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.tenant_id = current_tenant_id.get() or "-"
        record.user_id = current_user_id.get() or "-"
        return True
