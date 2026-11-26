from rest_framework import serializers

from tenants import jobs
from tenants.models import Site, User


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "name", "address", "created_at"]
        read_only_fields = ["id", "created_at"]


class MeSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "role", "tenant_id", "tenant_name"]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class PersonSerializer(serializers.ModelSerializer):
    """Ligne courte de l'annuaire : de quoi afficher « Yao Kouassi (op1) » partout."""

    full_name = serializers.CharField(read_only=True)
    job_title_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "job_title_label", "is_active"]

    def get_job_title_label(self, obj):
        return jobs.label(obj.job_title, obj.job_title_other)


class UserCardSerializer(PersonSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    manager = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "job_title", "job_title_other",
                  "job_title_label", "phone", "email", "role", "role_label", "manager", "is_active",
                  "last_login", "date_joined"]

    def get_manager(self, obj):
        m = obj.manager
        return {"id": str(m.id), "username": m.username, "full_name": m.full_name} if m else None


class UserWriteSerializer(serializers.Serializer):
    """Entree de l'ecran Utilisateurs. Les regles (liste des postes, superieur, mot de passe) sont dans
    tenants/services.py. Le superieur est cherche par le service dans l'entreprise de l'admin."""

    username = serializers.RegexField(r"^[\w.@+-]+$", max_length=150, required=False)
    password = serializers.CharField(write_only=True, trim_whitespace=False, required=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    job_title = serializers.CharField(max_length=40, required=False, allow_blank=True)
    job_title_other = serializers.CharField(max_length=100, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=User.Role.choices, required=False)
    manager = serializers.UUIDField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
