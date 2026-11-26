from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor


def ensure_database_migrated():
    """Juste apres « docker compose up -d » ou « restart », le conteneur peut encore jouer ses
    migrations. Une commande lancee a ce moment planterait avec une erreur incomprehensible."""
    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise CommandError(
            "La base n'est pas encore à jour : l'API est en train de démarrer. "
            "Lance « docker compose up -d --wait », attends qu'il rende la main, puis relance cette commande."
        )
