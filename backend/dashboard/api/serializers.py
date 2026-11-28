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
