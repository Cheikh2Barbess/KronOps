"""Validation des entrees et mise en forme des sorties. Aucune regle metier ici (voir services.py)."""

from rest_framework import serializers

from lots import services
from lots.models import ApprovalRequest, Lot, Movement


class ReceptionSerializer(serializers.Serializer):
    article = serializers.UUIDField()
    supplier = serializers.UUIDField()
    supplier_lot_code = serializers.CharField(max_length=100, allow_blank=True, required=False, default="")
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3)
    unit = serializers.CharField(max_length=30, help_text="Unité de base (kg, l, unite) ou conditionnement (sac...)")
    date_type = serializers.ChoiceField(choices=Lot.DateType.choices, required=False, allow_blank=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    temperature_c = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True)
    visual_ok = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    occurred_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Date réelle, pour une ressaisie de fiche papier"
    )


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class MovementSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    partner_name = serializers.CharField(source="partner.name", default=None, read_only=True)

    class Meta:
        model = Movement
        fields = [
            "id", "movement_type", "quantity", "partner", "partner_name", "reverses", "reason",
            "occurred_at", "created_at", "username",
        ]

    def get_username(self, obj):
        return obj.user.username if obj.user else None


class LotSerializer(serializers.ModelSerializer):
    article_code = serializers.CharField(source="article.code", read_only=True)
    article_name = serializers.CharField(source="article.name", read_only=True)
    base_unit = serializers.CharField(source="article.base_unit", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", default=None, read_only=True)
    balance = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)
    depleted = serializers.SerializerMethodField()
    expired = serializers.SerializerMethodField()

    class Meta:
        model = Lot
        fields = [
            "id", "code", "article", "article_code", "article_name", "base_unit", "supplier", "supplier_name",
            "supplier_lot_code", "date_type", "expiry_date", "production_date", "status", "block_reason",
            "balance", "depleted", "expired", "reception_temperature_c", "reception_visual_ok", "created_at",
        ]

    def get_depleted(self, obj):
        return obj.balance == 0

    def get_expired(self, obj):
        return services.is_expired(obj)


class LotDetailSerializer(LotSerializer):
    movements = serializers.SerializerMethodField()

    class Meta(LotSerializer.Meta):
        fields = LotSerializer.Meta.fields + ["movements"]

    def get_movements(self, obj):
        from lots.selectors import movements_of

        return MovementSerializer(movements_of(lot=obj), many=True).data


class TraceLotSerializer(LotSerializer):
    depth = serializers.IntegerField(read_only=True, default=0)

    class Meta(LotSerializer.Meta):
        fields = LotSerializer.Meta.fields + ["depth"]


class ShipmentSerializer(serializers.Serializer):
    movement_id = serializers.UUIDField(source="id")
    lot_id = serializers.UUIDField()
    lot_code = serializers.CharField(source="lot.code")
    customer_id = serializers.UUIDField(source="partner_id")
    customer_name = serializers.CharField(source="partner.name", default=None)
    customer_address = serializers.CharField(source="partner.address", default=None)
    customer_phone = serializers.CharField(source="partner.phone", default=None)
    customer_email = serializers.CharField(source="partner.email", default=None)
    quantity = serializers.SerializerMethodField()
    occurred_at = serializers.DateTimeField()

    def get_quantity(self, obj):
        return str(-obj.quantity)  # sortie stockee en negatif


class TraceQuerySerializer(serializers.Serializer):
    lot = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, help_text="Code interne ou n° de lot fournisseur, exact")

    def validate(self, data):
        if not data.get("lot") and not data.get("search"):
            raise serializers.ValidationError("Indiquer un lot (lot=...) ou un code (search=...).")
        return data


class ApprovalCreateSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ApprovalRequest.Action.choices)
    lot = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=3, required=False, allow_null=True,
        help_text="Unité de base de l'article. Rebut : positive. Ajustement : positive (ajout) ou négative (retrait).",
    )
    reason = serializers.CharField(allow_blank=True, trim_whitespace=True)


class ApprovalDecisionSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class ApprovalStatusFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ApprovalRequest.Status.choices, required=False)


class ApprovalSerializer(serializers.ModelSerializer):
    lot_code = serializers.CharField(source="lot.code", read_only=True)
    lot_status = serializers.CharField(source="lot.status", read_only=True)
    article_name = serializers.CharField(source="lot.article.name", read_only=True)
    base_unit = serializers.CharField(source="lot.article.base_unit", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)
    decided_by_username = serializers.CharField(source="decided_by.username", default=None, read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id", "action", "lot", "lot_code", "lot_status", "article_name", "base_unit", "quantity", "reason",
            "status", "requested_by_username", "requested_role", "decided_by_username", "decided_role",
            "decided_at", "decision_comment", "created_at",
        ]
