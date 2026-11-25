import uuid

from django.db import models


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TenantModel(UUIDModel):
    """Base de TOUT modele metier.

    Chaque table qui en herite DOIT avoir la Row-Level Security activee dans sa migration
    (voir core/rls.py). Le test core/tests/test_rls_coverage.py echoue sinon.
    tenant_id ne doit jamais venir de l'URL ni du corps de la requete : il vient de
    l'utilisateur connecte (request.user.tenant_id).
    """

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
