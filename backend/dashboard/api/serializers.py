from rest_framework import serializers

from dashboard.selectors import PERIODS


class DashboardQuerySerializer(serializers.Serializer):
    days = serializers.ChoiceField(choices=PERIODS, required=False)


class ThresholdSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    unit = serializers.CharField()
    direction = serializers.CharField()
    help = serializers.CharField()
    green = serializers.DecimalField(max_digits=12, decimal_places=2)
    red = serializers.DecimalField(max_digits=12, decimal_places=2)
    default_green = serializers.DecimalField(max_digits=12, decimal_places=2)
    default_red = serializers.DecimalField(max_digits=12, decimal_places=2)
    is_default = serializers.BooleanField()


class ThresholdWriteSerializer(serializers.Serializer):
    green = serializers.DecimalField(max_digits=12, decimal_places=2)
    red = serializers.DecimalField(max_digits=12, decimal_places=2)


class TargetWriteSerializer(serializers.Serializer):
    article = serializers.UUIDField()
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    months = serializers.ListField(child=serializers.CharField(allow_null=True, allow_blank=True), min_length=12,
                                   max_length=12, help_text="12 cibles en unité de base, vide ou null : pas de cible")


class TargetQuerySerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100, required=False)


class GapQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=["jour", "semaine", "mois"], required=False, default="mois")
