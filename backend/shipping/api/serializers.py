"""Validation des entrees et mise en forme des sorties. Aucune regle metier ici (voir services.py)."""

from rest_framework import serializers

from lots import reasons as lot_reasons


class LineWriteSerializer(serializers.Serializer):
    lot = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3)
    unit = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")


class ShipmentCreateSerializer(serializers.Serializer):
    customer = serializers.UUIDField()
    site = serializers.UUIDField(required=False, allow_null=True)
    lines = LineWriteSerializer(many=True)
    shipped_at = serializers.DateTimeField(required=False, allow_null=True)
    container_number = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    seal_number = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    export_document_ref = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    bill_of_lading = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    late_reason_code = serializers.ChoiceField(choices=list(lot_reasons.LATE_ENTRY), required=False, allow_blank=True,
                                               default="")
    late_comment = serializers.CharField(required=False, allow_blank=True, default="")


class LineSerializer(serializers.Serializer):
    lot_id = serializers.UUIDField(source="lot.id")
    lot_code = serializers.CharField(source="lot.code")
    article_code = serializers.CharField(source="lot.article.code")
    article_name = serializers.CharField(source="lot.article.name")
    base_unit = serializers.CharField(source="lot.article.base_unit")
    organic_status = serializers.CharField(source="lot.organic_status")
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    movement_id = serializers.UUIDField(source="movement.id")
    reversed = serializers.SerializerMethodField()

    def get_reversed(self, line):
        return hasattr(line.movement, "reversed_by")


class ShipmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    customer_id = serializers.UUIDField(source="customer.id")
    customer_name = serializers.CharField(source="customer.name")
    customer_city = serializers.CharField(source="customer.city")
    site_name = serializers.CharField(source="site.name", default=None)
    shipped_at = serializers.DateTimeField()
    container_number = serializers.CharField()
    seal_number = serializers.CharField()
    export_document_ref = serializers.CharField()
    bill_of_lading = serializers.CharField()
    lines = LineSerializer(many=True, source="lines.all")
    username = serializers.CharField(source="user.username", default=None)
    created_at = serializers.DateTimeField()
    late_reason_code = serializers.CharField()
