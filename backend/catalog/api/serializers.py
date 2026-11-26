"""Validation des entrees et mise en forme des sorties. Aucune regle metier ici (voir services.py)."""

from rest_framework import serializers

from catalog.models import Allergen, Article, Partner, UnitConversion


class AllergenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Allergen
        fields = ["code", "name", "order"]


class ArticleSerializer(serializers.ModelSerializer):
    allergens = serializers.DictField(
        child=serializers.CharField(), required=False, allow_null=True,
        help_text="Pour une matière : {code_allergène: contient | peut_contenir | absent}, les 14 codes.",
    )

    class Meta:
        model = Article
        fields = [
            "id", "code", "name", "article_type", "base_unit", "shelf_life_days", "storage",
            "is_active", "allergens_declared", "allergens", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "allergens_declared", "created_at", "updated_at"]
        # L'unicite du code est verifiee par le service (le tenant n'est pas dans la requete).
        validators = []

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.allergens_declared:
            rows = sorted(instance.allergen_rows.all(), key=lambda r: r.allergen.order)
            data["allergens"] = {r.allergen.code: r.presence for r in rows}
        else:
            data["allergens"] = None
        return data


class UnitConversionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitConversion
        fields = ["id", "unit_name", "factor", "created_at"]
        read_only_fields = ["id", "created_at"]
        validators = []

    def validate_factor(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le facteur doit être strictement positif.")
        return value


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = [
            "id", "name", "is_supplier", "is_customer", "address", "contact_name", "phone", "email",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        validators = []


class ImportFileSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Fichier CSV, séparateur ; ou , (UTF-8 ou export Excel Windows).")
