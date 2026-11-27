"""Validation des entrees et mise en forme des sorties. Aucune regle metier ici (voir services.py)."""

from rest_framework import serializers

from lots import reasons as lot_reasons
from lots.models import Lot
from production import reasons
from production.models import Equipment, ProductionRun


class EquipmentSerializer(serializers.ModelSerializer):
    site = serializers.UUIDField(source="site_id", required=False, allow_null=True)
    site_name = serializers.CharField(source="site.name", default=None, read_only=True)

    class Meta:
        model = Equipment
        fields = ["id", "code", "name", "equipment_type", "site", "site_name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
        validators = []


class RunInputWriteSerializer(serializers.Serializer):
    lot = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=15, decimal_places=3, help_text="Unité de base du lot (kg...)")


class RunCreateSerializer(serializers.Serializer):
    step = serializers.ChoiceField(choices=ProductionRun.Step.choices)
    equipment = serializers.UUIDField(required=False, allow_null=True)
    site = serializers.UUIDField(required=False, allow_null=True)
    inputs = RunInputWriteSerializer(many=True)
    output_article = serializers.UUIDField()
    output_quantity = serializers.DecimalField(max_digits=15, decimal_places=3)
    output_unit = serializers.CharField(max_length=30, required=False, allow_blank=True, default="",
                                        help_text="Unité de base ou conditionnement (carton...)")
    waste_quantity = serializers.DecimalField(max_digits=15, decimal_places=3, required=False, allow_null=True)
    waste_code = serializers.ChoiceField(choices=list(reasons.WASTE), required=False, allow_blank=True, default="")
    waste_comment = serializers.CharField(required=False, allow_blank=True, default="")
    started_at = serializers.DateTimeField(required=False, allow_null=True)
    ended_at = serializers.DateTimeField(required=False, allow_null=True,
                                         help_text="Vide : l'heure du serveur (saisie au moment du geste).")
    date_type = serializers.ChoiceField(choices=Lot.DateType.choices, required=False, allow_blank=True, default="")
    expiry_date = serializers.DateField(required=False, allow_null=True)
    late_reason_code = serializers.ChoiceField(choices=list(lot_reasons.LATE_ENTRY), required=False, allow_blank=True,
                                               default="")
    late_comment = serializers.CharField(required=False, allow_blank=True, default="")


class RunInputSerializer(serializers.Serializer):
    lot_id = serializers.UUIDField(source="lot.id")
    lot_code = serializers.CharField(source="lot.code")
    article_code = serializers.CharField(source="lot.article.code")
    article_name = serializers.CharField(source="lot.article.name")
    base_unit = serializers.CharField(source="lot.article.base_unit")
    organic_status = serializers.CharField(source="lot.organic_status")
    parcel_code = serializers.CharField(source="lot.parcel.code", default=None)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=3)


class RunSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    step = serializers.CharField()
    step_label = serializers.CharField(source="get_step_display")
    equipment_code = serializers.CharField(source="equipment.code", default=None)
    equipment_name = serializers.CharField(source="equipment.name", default=None)
    site_name = serializers.CharField(source="site.name", default=None)
    output_lot_id = serializers.UUIDField(source="output_lot.id")
    output_lot_code = serializers.CharField(source="output_lot.code")
    output_article_code = serializers.CharField(source="output_lot.article.code")
    output_article_name = serializers.CharField(source="output_lot.article.name")
    organic_status = serializers.CharField(source="output_lot.organic_status")
    base_unit = serializers.CharField(source="output_lot.article.base_unit")
    inputs = RunInputSerializer(many=True, source="inputs.all")
    input_quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    output_quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    waste_quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    waste_code = serializers.CharField()
    waste_label = serializers.SerializerMethodField()
    unexplained_quantity = serializers.DecimalField(max_digits=18, decimal_places=3, allow_null=True)
    yield_pct = serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True)
    yield_min_pct = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    yield_max_pct = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    yield_status = serializers.CharField()
    started_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    late = serializers.BooleanField()
    late_reason_code = serializers.CharField()
    late_reason_label = serializers.SerializerMethodField()
    username = serializers.CharField(source="user.username", default=None)
    cancelled = serializers.SerializerMethodField()
    cancellable = serializers.SerializerMethodField()

    def get_cancellable(self, run):
        return getattr(run, "cancellable", None)

    def get_cancelled(self, run):
        c = getattr(run, "cancelled", None)
        if c is None:
            return None
        return {"at": c.created_at, "by": c.user.username if c.user else None, "reason_code": c.reason_code,
                "reason": lot_reasons.text(reasons.RUN_CANCEL, c.reason_code, c.comment)}

    def get_waste_label(self, run):
        return lot_reasons.text(reasons.WASTE, run.waste_code, run.waste_comment) if run.waste_code else ""

    def get_late_reason_label(self, run):
        if not run.late_reason_code:
            return ""
        return lot_reasons.text(lot_reasons.LATE_ENTRY, run.late_reason_code, run.late_comment)


class BalanceFilterSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    step = serializers.ChoiceField(choices=ProductionRun.Step.choices, required=False)
    site = serializers.UUIDField(required=False)


class StepTotalSerializer(serializers.Serializer):
    step = serializers.CharField()
    step_label = serializers.CharField()
    unit = serializers.CharField()
    runs = serializers.IntegerField()
    input_quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    output_quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    waste_quantity = serializers.DecimalField(max_digits=18, decimal_places=3)
    yield_pct = serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True)
    deviations = serializers.IntegerField()
    late_entries = serializers.IntegerField()


class AvailableLotSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    article_code = serializers.CharField(source="article.code")
    article_name = serializers.CharField(source="article.name")
    article_type = serializers.CharField(source="article.article_type")
    base_unit = serializers.CharField(source="article.base_unit")
    organic_status = serializers.CharField()
    parcel_code = serializers.CharField(source="parcel.code", default=None)
    site = serializers.UUIDField(source="site_id", allow_null=True)
    site_name = serializers.CharField(source="site.name", default=None)
    balance = serializers.DecimalField(max_digits=18, decimal_places=3)


class RunCancelSerializer(serializers.Serializer):
    reason_code = serializers.ChoiceField(choices=list(reasons.RUN_CANCEL))
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class StepSettingSerializer(serializers.Serializer):
    code = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    position = serializers.IntegerField(read_only=True)


class StepChoiceSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    is_active = serializers.BooleanField()


class StepConfigureSerializer(serializers.Serializer):
    """Liste ordonnee des etapes voulues. Les etapes non citees sont desactivees."""

    steps = StepChoiceSerializer(many=True, allow_empty=True)


class RouteSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    steps = serializers.ListField(source="step_rows", child=serializers.DictField(), read_only=True)
    articles = serializers.SerializerMethodField()

    def get_articles(self, route):
        return [{"id": str(a["id"]), "code": a["code"], "name": a["name"]} for a in route.article_rows]


class RouteWriteSerializer(serializers.Serializer):
    """Parcours complet : nom, etat, etapes permises (codes) et articles rattaches (identifiants)."""

    name = serializers.CharField(max_length=100, allow_blank=True, trim_whitespace=True)
    is_active = serializers.BooleanField(default=True)
    steps = serializers.ListField(child=serializers.CharField(max_length=20), allow_empty=True)
    articles = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
