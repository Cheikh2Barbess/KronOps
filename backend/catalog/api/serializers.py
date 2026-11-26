"""Validation des entrees et mise en forme des sorties. Aucune regle metier ici (voir services.py)."""

from rest_framework import serializers

from catalog.models import Allergen, Article, ArticleAllergen, Partner, UnitConversion


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
            "id", "name", "is_supplier", "is_customer", "address", "city", "contact_name", "phone", "email",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        validators = []


class ImportFileSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Fichier CSV, séparateur ; ou , (UTF-8 ou export Excel Windows).")


# Filtres des listes -------------------------------------------------------------
# Plusieurs valeurs dans un meme filtre : separees par des virgules, combinees en OU.
# Filtres differents : combines en ET.


class CommaListField(serializers.CharField):
    def __init__(self, *, choices=None, **kwargs):
        self.allowed = choices
        super().__init__(required=False, **kwargs)

    def to_internal_value(self, data):
        values = [v.strip() for v in super().to_internal_value(data).split(",") if v.strip()]
        allowed = self.allowed() if callable(self.allowed) else self.allowed
        if allowed is not None:
            unknown = [v for v in values if v not in allowed]
            if unknown:
                raise serializers.ValidationError(f"Valeur inconnue : {', '.join(unknown)}.")
        return values


class YesNoField(serializers.ChoiceField):
    """true/false dans l'URL. Absent = pas de filtre (le BooleanField de DRF lirait « faux »)."""

    def __init__(self, **kwargs):
        super().__init__(choices=["true", "false", "1", "0", "oui", "non"], required=False, **kwargs)

    def to_internal_value(self, data):
        return super().to_internal_value(str(data).lower()) in {"true", "1", "oui"}


def _allergen_codes():
    from catalog.selectors import allergen_codes

    return allergen_codes()


class ArticleFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, max_length=100, help_text="Texte cherché dans le code ou le nom.")
    type = CommaListField(choices=Article.Type.values)
    storage = CommaListField(choices=Article.Storage.values)
    active = YesNoField()
    allergen = CommaListField(choices=_allergen_codes, help_text="Contient l'un de ces allergènes.")
    presence = serializers.ChoiceField(
        choices=["present", ArticleAllergen.Presence.CONTIENT, ArticleAllergen.Presence.PEUT_CONTENIR],
        required=False, default="present", help_text="present = contient ou peut contenir.",
    )
    allergen_free = CommaListField(choices=_allergen_codes, help_text="Déclaré absent pour tous ces allergènes.")
    has_allergen = YesNoField(help_text="true : au moins un allergène présent. false : déclaré, tout absent.")


class PartnerFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, max_length=100, help_text="Nom, contact, adresse ou ville.")
    role = serializers.ChoiceField(choices=["supplier", "customer", "both"], required=False)
    city = CommaListField(help_text="Ville, sans tenir compte des majuscules.")
    active = YesNoField()


class CitySerializer(serializers.Serializer):
    city = serializers.CharField()
    count = serializers.IntegerField()
