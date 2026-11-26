# Motifs codes (listes fermees) pour le blocage et la double validation, decision du proprietaire du 26/11/2026.
# Les demandes deja saisies gardent leur motif libre, recopie dans « precision », avec le code « autre ».
from django.db import migrations, models

# La recopie respecte la Row-Level Security : elle se fait entreprise par entreprise, avec le meme
# reglage app.tenant_id que l'application (voir core/tenancy.py). Aucune politique n'est levee.
COPY_FREE_TEXT = """
DO $$
DECLARE t uuid;
BEGIN
  FOR t IN SELECT id FROM tenants_tenant LOOP
    PERFORM set_config('app.tenant_id', t::text, true);
    UPDATE lots_approvalrequest SET comment = reason;
  END LOOP;
  PERFORM set_config('app.tenant_id', '', true);
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("lots", "0002_approval_requests"), ("tenants", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="lot",
            name="block_code",
            field=models.CharField(blank=True, max_length=40, verbose_name="code du motif de blocage"),
        ),
        migrations.AlterField(
            model_name="lot",
            name="block_reason",
            field=models.TextField(blank=True, verbose_name="motif de blocage (libellé et précision)"),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="reason_code",
            field=models.CharField(default="autre", max_length=40, verbose_name="motif (code)"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="comment",
            field=models.TextField(blank=True, verbose_name="précision"),
        ),
        migrations.RunSQL(COPY_FREE_TEXT, reverse_sql=migrations.RunSQL.noop),
        migrations.RemoveField(model_name="approvalrequest", name="reason"),
        migrations.AddField(
            model_name="approvalrequest",
            name="decision_code",
            field=models.CharField(blank=True, max_length=40, verbose_name="motif du refus (code)"),
        ),
        migrations.AlterField(
            model_name="approvalrequest",
            name="decision_comment",
            field=models.TextField(blank=True, verbose_name="précision du refus"),
        ),
    ]
