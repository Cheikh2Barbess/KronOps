from rest_framework import serializers

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
