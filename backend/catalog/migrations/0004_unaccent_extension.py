# Recherche insensible aux accents (« cooperative » trouve « Coopérative »).
# unaccent est une extension « de confiance » depuis PostgreSQL 13 : le role proprietaire
# de la base peut la creer sans etre superutilisateur.
from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_partner_city_and_filter_indexes")]

    operations = [UnaccentExtension()]
