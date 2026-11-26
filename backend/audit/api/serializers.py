from django.apps import apps
from rest_framework import serializers

from audit.models import AuditLog
from audit.selectors import entry_uuids


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
    subject = serializers.SerializerMethodField(help_text="L'objet en clair : code du lot, nom de l'article...")
    unit = serializers.SerializerMethodField(help_text="Unité de base des quantités de la ligne, si elle en a.")
    refs = serializers.SerializerMethodField(help_text="Noms lisibles des identifiants cités dans la ligne.")

    class Meta:
        model = AuditLog
        fields = [
            "id", "created_at", "action", "entity_type", "entity_label", "entity_id",
            "user_id", "username", "old_values", "new_values", "changed_fields", "subject", "unit", "refs",
        ]

    def get_username(self, obj):
        return obj.user.username if obj.user else None

    def get_entity_label(self, obj):
        return entity_label(obj.entity_type)

    def _subject(self, obj):
        return self.context.get("subjects", {}).get(obj.pk, {})

    def get_subject(self, obj):
        return self._subject(obj).get("subject", "")

    def get_unit(self, obj):
        return self._subject(obj).get("unit")

    def get_refs(self, obj):
        names = self.context.get("names", {})
        return {uuid: names[uuid] for uuid in entry_uuids(obj) if uuid in names}

    def get_changed_fields(self, obj):
        old, new = obj.old_values or {}, obj.new_values or {}
        if not old:
            return []
        return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


class AuditUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
