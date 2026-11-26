# Tracalys : règles pour l'assistant IA

Tracalys (anciennement KronOps) est un MES SaaS pour l'agroalimentaire (PME, Côte d'Ivoire en premier), priorité à la traçabilité des lots.
Stack phase 1 : Django 5.2 LTS + Django REST Framework + PostgreSQL 17, front Next.js, Docker Compose.
Spécification de référence : le PRD phase 1 et son onglet « Architecture technique » (gelés). En cas de doute, le PRD prime sur ton intuition.

## Règles obligatoires

1. La logique métier va uniquement dans `services.py`, dans `@transaction.atomic`. Les vues et les serializers valident l'entrée et appellent un service, rien d'autre. Les lectures complexes vont dans `selectors.py`.
2. Chaque modèle métier hérite de `core.models.TenantModel` (id UUID, `tenant_id`). Ne jamais lire `tenant_id` depuis l'URL ou le corps de la requête : il vient de `request.user.tenant_id`.
3. Toute vue de l'API métier hérite de `core.api.TenantAPIView`. Ne jamais désactiver ni contourner la Row-Level Security.
4. Toute nouvelle table qui porte `tenant_id` reçoit `enable_rls("<table>")` (voir `core/rls.py`) dans sa migration. Le test `core/tests/test_rls_coverage.py` échoue sinon. Ne pas ajouter d'exception à ce test sans décision écrite du propriétaire.
5. Les tables `Movement`, `LotLink` et `AuditLog` sont en insertion seule : jamais d'`update()`, de `delete()` ni de `save()` sur une ligne existante. Une correction est un nouvel enregistrement. Toute nouvelle table de ce type reçoit `make_append_only("<table>")` dans sa migration.
6. Toute action métier appelle `publish_event()` dans la même transaction, et `record_audit()` quand elle modifie une donnée.
7. N'ajoute aucune dépendance (Redis, Celery, JWT, GraphQL, bibliothèque front, etc.) sans demander au propriétaire. Le PRD liste ce qui est repoussé aux phases 2 et 3.
8. Écris d'abord les tests pytest des critères d'acceptation de la user story, puis le code. Toujours au moins un test d'isolation entre deux tenants par nouvel endpoint (l'objet d'un autre client renvoie 404).
9. Si tu n'es pas sûr qu'une fonction, une option ou une API existe, dis-le au lieu de l'inventer.

## Exception connue

La table `tenants_user` n'a pas de RLS : la connexion doit trouver l'utilisateur avant de connaître son entreprise. Toute lecture d'utilisateurs dans l'API passe par `tenants/selectors.py`, qui filtre par `tenant_id`.

## Base de données : deux rôles

- Rôle propriétaire (`DB_OWNER_USER`) : joue les migrations et les tests.
- Rôle applicatif (`DB_USER`, par défaut `kronops_app`) : utilisé par l'API. Ni superutilisateur, ni `BYPASSRLS`, ni propriétaire des tables.
- Les tests basculent sur le rôle applicatif (`conftest.py`). Ne retire pas ce mécanisme.
- Hors requête HTTP (commande, script, test), utilise `core.tenancy.tenant_context(tenant_id)` avant de lire ou écrire une table protégée.

## Commandes utiles

- Tout lancer : `docker compose up --build`
- Tests : `./scripts/test.sh` (ou `./scripts/test.sh -k isolation` pour une partie)
- Nouvelle migration : `docker compose exec backend python manage.py makemigrations`
- Créer une entreprise : `docker compose exec backend python manage.py create_tenant --name "Nom" --admin identifiant`

## Méthode de travail

- Une user story du PRD = une branche Git = une session.
- Les tests doivent passer avant toute pull request. La CI GitHub les relance à chaque push.
- Ne modifie jamais une migration déjà fusionnée dans `main` : crée-en une nouvelle.
