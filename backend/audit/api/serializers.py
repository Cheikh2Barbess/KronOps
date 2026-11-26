from django.apps import apps
from rest_framework import serializers

from audit.models import AuditLog


def entity_label(entity_type):
    try:
        return str(apps.get_model(entity_type)._meta.verbose_name)
    except (LookupError, ValueError):
        return entity_type


class AuditFilterSerializer(serializers.Serializer):
    entity_type = serializers.CharField(required=False)
    entity_id = serializers.UUIDField(required=False)
    action = serializers.CharField(required=False)
    user = serializers.UUIDField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class AuditEntrySerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    entity_label = serializers.SerializerMethodField()
    changed_fields = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id", "created_at", "action", "entity_type", "entity_label", "entity_id",
            "user_id", "username", "old_values", "new_values", "changed_fields",
        ]

    def get_username(self, obj):
        return obj.user.username if obj.user else None

    def get_entity_label(self, obj):
        return entity_label(obj.entity_type)

    def get_changed_fields(self, obj):
        old, new = obj.old_values or {}, obj.new_values or {}
        if not old:
            return []
        return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


class AuditUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
