"""Liste de reference des 14 allergenes de l'annexe II du reglement (UE) n° 1169/2011.

Le role applicatif peut seulement la lire : une modification passe par une nouvelle migration.
"""

import uuid

from django.conf import settings
from django.db import migrations

REGULATION = "UE_1169_2011"

# (code, libelle) dans l'ordre de l'annexe II.
EU_ALLERGENS = [
    ("gluten", "Céréales contenant du gluten (blé, épeautre, blé de Khorasan, seigle, orge, avoine)"),
    ("crustaces", "Crustacés"),
    ("oeufs", "Œufs"),
    ("poissons", "Poissons"),
    ("arachides", "Arachides"),
    ("soja", "Soja"),
    ("lait", "Lait (y compris lactose)"),
    ("fruits_a_coque", "Fruits à coque (amandes, noisettes, noix, cajou, pécan, noix du Brésil, pistaches, macadamia)"),
    ("celeri", "Céleri"),
    ("moutarde", "Moutarde"),
    ("sesame", "Graines de sésame"),
    ("sulfites", "Anhydride sulfureux et sulfites (plus de 10 mg/kg ou 10 mg/L en SO2)"),
    ("lupin", "Lupin"),
    ("mollusques", "Mollusques"),
]


def load(apps, schema_editor):
    Allergen = apps.get_model("catalog", "Allergen")
    for order, (code, name) in enumerate(EU_ALLERGENS, start=1):
        Allergen.objects.create(id=uuid.uuid4(), regulation=REGULATION, code=code, name=name, order=order)


def unload(apps, schema_editor):
    apps.get_model("catalog", "Allergen").objects.filter(regulation=REGULATION).delete()


ROLE = settings.DB_APP_ROLE


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.RunPython(load, unload),
        migrations.RunSQL(
            sql=f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON catalog_allergen FROM {ROLE};",
            reverse_sql=f"GRANT INSERT, UPDATE, DELETE ON catalog_allergen TO {ROLE};",
        ),
    ]
