"""Lectures des expeditions. La RLS de PostgreSQL filtre par client."""

from django.db.models import Prefetch
from django.http import Http404

from shipping.models import Shipment, ShipmentLine


def shipments(*, container=None, customer_id=None):
    lines = ShipmentLine.objects.select_related("lot__article", "movement").order_by("lot__code")
    qs = (
        Shipment.objects.select_related("customer", "site", "user")
        .prefetch_related(Prefetch("lines", queryset=lines))
        .order_by("-shipped_at", "-created_at")
    )
    if container:
        qs = qs.filter(container_number__icontains=container.replace(" ", ""))
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    return qs


def shipment_or_404(*, shipment_id):
    shipment = shipments().filter(pk=shipment_id).first()
    if shipment is None:
        raise Http404
    return shipment
