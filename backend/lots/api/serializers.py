"""Validation des entrees et mise en forme des sorties. Aucune regle metier ici (voir services.py)."""

from rest_framework import serializers

from catalog.models import OrganicStatus
from lots import reasons, services
from lots.models import ApprovalRequest, Lot, Movement, QualityCheck


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
    reason_code = serializers.ChoiceField(choices=list(reasons.RECEPTION), required=False, allow_blank=True, default="",
                                          help_text="Obligatoire si visual_ok est faux. Voir approvals/reasons/ (reception).")
    comment = serializers.CharField(required=False, allow_blank=True, default="", help_text="Obligatoire pour « autre ».")
    occurred_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Date réelle, pour une ressaisie de fiche papier"
    )
    parcel = serializers.UUIDField(required=False, allow_null=True,
                                   help_text="Parcelle du fournisseur. Son statut bio est recopié sur le lot.")
    organic_status = serializers.ChoiceField(
        choices=OrganicStatus.choices, required=False, allow_blank=True, default="",
        help_text="Obligatoire sans parcelle, sauf pour un emballage.",
    )
    site = serializers.UUIDField(required=False, allow_null=True, help_text="Obligatoire si l'entreprise a plusieurs sites.")
    late_reason_code = serializers.ChoiceField(choices=list(reasons.LATE_ENTRY), required=False, allow_blank=True,
                                               default="", help_text="Obligatoire si la date réelle a plus de 2 heures.")
    late_comment = serializers.CharField(required=False, allow_blank=True, default="")


class ConversionOptionSerializer(serializers.Serializer):
    unit_name = serializers.CharField()
    factor = serializers.DecimalField(max_digits=18, decimal_places=6)


class ReceptionArticleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    article_type = serializers.CharField()
    base_unit = serializers.CharField()
    storage = serializers.CharField()
    conversions = ConversionOptionSerializer(many=True, source="conversions.all")


class ReceptionParcelSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    locality = serializers.CharField()
    organic_status = serializers.CharField()


class ReceptionSupplierSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    city = serializers.CharField()
    parcels = ReceptionParcelSerializer(many=True, source="active_parcels")


class ReceptionRowSerializer(serializers.Serializer):
    movement_id = serializers.UUIDField(source="id")
    lot_id = serializers.UUIDField(source="lot.id")
    lot_code = serializers.CharField(source="lot.code")
    lot_status = serializers.CharField(source="lot.status")
    article_code = serializers.CharField(source="lot.article.code")
    article_name = serializers.CharField(source="lot.article.name")
    base_unit = serializers.CharField(source="lot.article.base_unit")
    supplier_name = serializers.CharField(source="partner.name", default=None)
    supplier_lot_code = serializers.CharField(source="lot.supplier_lot_code")
    organic_status = serializers.CharField(source="lot.organic_status")
    parcel_code = serializers.CharField(source="lot.parcel.code", default=None)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    block_reason = serializers.CharField(source="lot.block_reason")
    occurred_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    username = serializers.CharField(source="user.username", default=None)
    reversed = serializers.BooleanField()
    reversal_reason = serializers.CharField(allow_null=True)
    can_reverse = serializers.BooleanField()
    late = serializers.SerializerMethodField()
    late_reason_code = serializers.CharField()

    def get_late(self, obj):
        return bool(obj.late_reason_code) or services.is_late(occurred_at=obj.occurred_at, created_at=obj.created_at)


class ReverseSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(choices=list(reasons.REVERSAL), help_text="Voir approvals/reasons/ (reversal).")
    comment = serializers.CharField(required=False, allow_blank=True, default="", help_text="Obligatoire pour « autre ».")


class MovementSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    partner_name = serializers.CharField(source="partner.name", default=None, read_only=True)

    class Meta:
        model = Movement
        fields = [
            "id", "movement_type", "quantity", "partner", "partner_name", "reverses", "reason", "reason_code",
            "occurred_at", "created_at", "username", "late_reason_code", "late_comment",
        ]

    def get_username(self, obj):
        return obj.user.username if obj.user else None


class LotSerializer(serializers.ModelSerializer):
    article_code = serializers.CharField(source="article.code", read_only=True)
    article_name = serializers.CharField(source="article.name", read_only=True)
    base_unit = serializers.CharField(source="article.base_unit", read_only=True)
    article_type = serializers.CharField(source="article.article_type", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", default=None, read_only=True)
    parcel_code = serializers.CharField(source="parcel.code", default=None, read_only=True)
    parcel_locality = serializers.CharField(source="parcel.locality", default=None, read_only=True)
    site_name = serializers.CharField(source="site.name", default=None, read_only=True)
    balance = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)
    depleted = serializers.SerializerMethodField()
    expired = serializers.SerializerMethodField()

    class Meta:
        model = Lot
        fields = [
            "id", "code", "article", "article_code", "article_name", "base_unit", "supplier", "supplier_name",
            "supplier_lot_code", "date_type", "expiry_date", "production_date", "status", "block_code", "block_reason",
            "balance", "depleted", "expired", "reception_temperature_c", "reception_visual_ok", "created_at",
            "organic_status", "parcel", "parcel_code", "parcel_locality", "site", "site_name", "article_type",
        ]

    def get_depleted(self, obj):
        return obj.balance == 0

    def get_expired(self, obj):
        return services.is_expired(obj)


class QualityCheckSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", default=None, read_only=True)

    class Meta:
        model = QualityCheck
        fields = ["id", "lot", "checks", "moisture_pct", "result", "comment", "checked_at", "created_at", "username"]


class QualityCheckCreateSerializer(serializers.Serializer):
    checks = serializers.DictField(child=serializers.ChoiceField(choices=["ok", "nok"]),
                                   help_text="{code_critère: ok | nok}. Voir lots/quality-checks/options/.")
    moisture_pct = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    checked_at = serializers.DateTimeField(required=False, allow_null=True)
    late_reason_code = serializers.ChoiceField(choices=list(reasons.LATE_ENTRY), required=False, allow_blank=True,
                                               default="")
    late_comment = serializers.CharField(required=False, allow_blank=True, default="")


class LotDetailSerializer(LotSerializer):
    movements = serializers.SerializerMethodField()
    quality_checks = serializers.SerializerMethodField()

    class Meta(LotSerializer.Meta):
        fields = LotSerializer.Meta.fields + ["movements", "quality_checks"]

    def get_quality_checks(self, obj):
        return QualityCheckSerializer(obj.quality_checks.select_related("user").order_by("-checked_at"), many=True).data

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


class BlockSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(choices=list(reasons.BLOCK))
    comment = serializers.CharField(required=False, allow_blank=True, default="", help_text="Obligatoire pour « autre ».")


class ApprovalCreateSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ApprovalRequest.Action.choices)
    lot = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=3, required=False, allow_null=True,
        help_text="Unité de base de l'article. Rebut : positive. Ajustement : positive (ajout) ou négative (retrait).",
    )
    reason_code = serializers.ChoiceField(choices=reasons.ALL_APPROVAL_CODES, help_text="Voir approvals/reasons/.")
    comment = serializers.CharField(required=False, allow_blank=True, default="", help_text="Obligatoire pour « autre ».")


class RejectSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(choices=list(reasons.REJECT))
    comment = serializers.CharField(required=False, allow_blank=True, default="", help_text="Obligatoire pour « autre ».")


class ApprovalStatusFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ApprovalRequest.Status.choices, required=False)


class ApprovalSerializer(serializers.ModelSerializer):
    lot_code = serializers.CharField(source="lot.code", read_only=True)
    lot_status = serializers.CharField(source="lot.status", read_only=True)
    article_name = serializers.CharField(source="lot.article.name", read_only=True)
    base_unit = serializers.CharField(source="lot.article.base_unit", read_only=True)
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)
    decided_by_username = serializers.CharField(source="decided_by.username", default=None, read_only=True)
    reason_label = serializers.SerializerMethodField()
    decision_label = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = [
            "id", "action", "lot", "lot_code", "lot_status", "article_name", "base_unit", "quantity", "reason_code",
            "reason_label", "comment", "status", "requested_by_username", "requested_role", "decided_by_username",
            "decided_role", "decided_at", "decision_code", "decision_label", "decision_comment", "created_at",
        ]

    def get_reason_label(self, obj):
        return reasons.APPROVAL[obj.action].get(obj.reason_code, obj.reason_code)

    def get_decision_label(self, obj):
        return reasons.REJECT.get(obj.decision_code, obj.decision_code) if obj.decision_code else ""


class RecallQuerySerializer(serializers.Serializer):
    search = serializers.CharField(help_text="Code de lot (carton, palette), n° de lot fournisseur ou n° de conteneur")


class RecallShipmentSerializer(serializers.Serializer):
    """Une expedition touchee par le rappel : client, quantite et, quand elle existe, l'expedition complete."""

    def to_representation(self, pair):
        movement, shipment = pair
        partner = movement.partner
        return {
            "movement_id": str(movement.id), "lot_id": str(movement.lot_id), "lot_code": movement.lot.code,
            "base_unit": movement.lot.article.base_unit, "quantity": str(-movement.quantity),
            "occurred_at": movement.occurred_at.isoformat(),
            "customer_name": partner.name if partner else None, "customer_address": partner.address if partner else None,
            "customer_city": partner.city if partner else None,
            "customer_phone": partner.phone if partner else None, "customer_email": partner.email if partner else None,
            "shipment_id": str(shipment.id) if shipment else None,
            "container_number": shipment.container_number if shipment else "",
            "seal_number": shipment.seal_number if shipment else "",
            "export_document_ref": shipment.export_document_ref if shipment else "",
            "bill_of_lading": shipment.bill_of_lading if shipment else "",
        }
