# KronOps

Logiciel de pilotage de production (MES) pour l'agroalimentaire, vendu en abonnement.
Ce dépôt contient le socle technique et les premières fonctions métier : les **référentiels** (US-02), l'écran du **journal d'audit** (US-03) et le **cœur des lots** : réception, mouvements en insertion seule, recherche amont et aval (US-14, US-15). Les lots, ordres de fabrication et expéditions ne sont pas encore écrits.

## Ce que le socle contient déjà

| Élément | À quoi ça sert |
|---|---|
| Entreprises clientes (tenants) | Chaque client a ses données, rangées dans la même base |
| Row-Level Security PostgreSQL | La base elle-même empêche un client de voir les données d'un autre, même si le code a un bug |
| Utilisateurs et rôles | Admin, Qualité, Production, Opérateur, Lecture (matrice des droits du PRD) |
| Connexion par cookie sécurisé | Le cookie de session est illisible par JavaScript et protégé contre le CSRF |
| Journal d'audit | Garde la trace de chaque action. La base refuse toute modification ou suppression |
| Table d'événements (outbox) | Chaque action laisse un événement, prêt pour les alertes de la phase 2 |
| Point de contrôle `/api/v1/health/` | Indique si le service et la base répondent |
| Documentation de l'API | Générée automatiquement, visible sur `/api/v1/docs/` |
| Référentiels (US-02) | Articles (matière, emballage, semi-fini, produit fini), allergènes obligatoires pour les matières (14 allergènes UE), conversions d'unités (1 sac = 25 kg), fournisseurs et clients, import CSV tout ou rien. Écran : http://localhost:3000/referentiels |
| Journal d'audit (US-03) | Qui a créé, modifié ou importé quoi, quand, avec l'ancienne et la nouvelle valeur. Filtres par objet, action, utilisateur et dates. Lecture seule, rôles Admin et Qualité. Écran : http://localhost:3000/journal |
| Lots et traçabilité | Réception d'un lot fournisseur (API seulement, l'écran attend les maquettes testées avec les opérateurs), stock par lot calculé depuis les mouvements, jamais négatif, blocage avec motif, annulation par contre-mouvement. Recherche aval (lot fournisseur vers lots produits et clients livrés) et amont. Écran : http://localhost:3000/tracabilite |
| Tests automatiques | 118 tests, dont l'isolation entre clients et l'immuabilité de l'audit |

## Lancer KronOps sur ton ordinateur

### 1. Installer les outils (une seule fois)

- **Docker Desktop** : https://www.docker.com/products/docker-desktop/ . Installe-le, puis ouvre-le et attends que la baleine en bas de l'écran indique « running ».
- **Git** : https://git-scm.com/downloads (déjà présent sur Mac en général).

### 2. Récupérer le code (une seule fois)

Ouvre un terminal (sur Mac : application « Terminal », sur Windows : « PowerShell ») et tape :

```
git clone https://github.com/Cheikh2Barbess/KronOps.git
cd KronOps
```

### 3. Créer le fichier de configuration (une seule fois)

```
cp .env.example .env
```

Sur Windows PowerShell, la commande est `copy .env.example .env`.
Ouvre ensuite le fichier `.env` avec un éditeur de texte (sur Windows : `notepad .env`) et remplace chaque `change-moi...` par un mot de passe de ton choix. **Ne change pas les noms d'utilisateur, et utilise uniquement des lettres et des chiffres dans les mots de passe.** Ce fichier reste sur ton ordinateur : il n'est jamais envoyé sur GitHub.

### 4. Démarrer

```
docker compose up --build
```

La première fois, ça prend plusieurs minutes (téléchargements). Quand le terminal affiche `Ready` et `Starting development server`, ouvre http://localhost:3000 dans ton navigateur. Tu dois voir « Service : ok · Base de données : ok ».

Pour arrêter : `Ctrl + C` dans le terminal, puis `docker compose down`.

### 5. Créer une première entreprise et son administrateur

Dans un **deuxième** terminal, dans le dossier KronOps :

```
docker compose exec backend python manage.py create_tenant --name "Ma Société" --admin patron
```

Le mot de passe est demandé au clavier (10 caractères minimum, rien ne s'affiche pendant la frappe, c'est normal). Retourne sur http://localhost:3000 et connecte-toi avec `patron`.

### 6. Lancer les tests

```
./scripts/test.sh
```

Sur Windows, utilise plutôt : `docker compose run --rm backend sh -c 'DB_USER=$DB_OWNER_USER DB_PASSWORD=$DB_OWNER_PASSWORD python -m pytest'`

Tu dois voir `118 passed` à la fin (ou `116 passed, 2 skipped` dans Docker). **Si un test échoue après une modification faite avec l'IA, la modification est fausse** : ne la garde pas.

### 7. Essayer les référentiels

1. Connecte-toi sur http://localhost:3000 puis clique sur « Référentiels ».
2. Dans « Articles », clique sur « Télécharger le modèle », puis importe ce même fichier : 5 articles apparaissent.
3. Ouvre le modèle dans Excel, vide les colonnes d'allergènes d'une matière, enregistre en CSV et importe-le : le fichier est refusé en entier, avec le numéro de ligne en erreur.
4. Fais de même avec le modèle « Fournisseurs et clients ».

Format du fichier articles : séparateur `;` ou `,`, une ligne d'en-tête. Colonnes obligatoires `code`, `nom`, `type` (matiere, emballage, semi_fini, fini), `unite` (kg, l, unite). Colonnes facultatives `duree_vie_jours`, `conservation` (ambiant, refrigere, congele) et une colonne par allergène (`gluten`, `crustaces`, `oeufs`, `poissons`, `arachides`, `soja`, `lait`, `fruits_a_coque`, `celeri`, `moutarde`, `sesame`, `sulfites`, `lupin`, `mollusques`) avec `contient`, `peut_contenir` ou `absent`. Pour une matière, les 14 colonnes sont obligatoires.

### 8. Écran rapide (mode production)

Par défaut, l'écran tourne en mode développement : chaque page est compilée à sa première visite, ce qui ralentit la navigation, surtout sous Docker Desktop Windows. Pour juger de la vraie vitesse, lance l'écran déjà compilé :

```
docker compose -f docker-compose.yml -f docker-compose.front-prod.yml up --build -d --wait
```

La première fois, la compilation prend une ou deux minutes. Ensuite, chaque modification du code de l'écran (par exemple après un `git pull`) demande de relancer la même commande. Pour revenir au mode développement : `docker compose up --build -d --wait`.

### 9. Essayer la traçabilité avec des données de démonstration

Les ordres de fabrication ne sont pas encore écrits. Une commande crée donc un petit jeu de démonstration (farine et beurre reçus, deux lots de biscuits, une expédition), avec des codes qui commencent par DEMO :

```
docker compose up --build -d --wait
docker compose exec backend python manage.py demo_tracabilite --admin patron
```

`--wait` rend la main seulement quand l'API a fini ses migrations et répond. Sans lui, la commande de démonstration peut arriver trop tôt : elle le dit et il suffit de la relancer 30 secondes plus tard.

Remplace `patron` par ton identifiant administrateur. Ouvre ensuite http://localhost:3000/tracabilite, cherche `DEMO-MOULIN-001` en aval : tu vois les deux lots de biscuits et le supermarché livré. Cherche ensuite le code du premier lot de biscuits en amont : tu retrouves la farine, le beurre et leurs fournisseurs.

### 10. Essayer la double validation (déblocage, destruction, rebut, ajustement)

Il faut au moins deux personnes de rôles différents. Ajoute d'abord des utilisateurs à ton entreprise (le mot de passe est demandé au clavier) :

```
docker compose exec backend python manage.py create_user --admin patron --username qualite1 --role qualite
docker compose exec backend python manage.py create_user --admin patron --username prod1 --role production
```

Rôles possibles : `admin`, `qualite`, `production`, `operateur`, `lecture`. Ensuite, sur http://localhost:3000/validations :

1. Connecté en `prod1`, cherche un lot et bloque-le (le blocage est immédiat).
2. Connecté en `qualite1`, demande « Débloquer le lot » avec un motif. Le lot reste bloqué : ta propre demande ne peut pas être validée par toi.
3. Connecté en `prod1` (ou `patron`), clique « Valider » : le lot redevient disponible. Le journal d'audit garde la demande et la validation.

Règles (matrice des droits du PRD) : déblocage et destruction sont demandés par la Qualité, le rebut par la Qualité, la Production ou un opérateur, l'ajustement par la Qualité ou la Production. Admin, Qualité et Production valident, jamais leur propre demande ni celle d'une personne du même rôle.

## En cas de problème

| Message | Cause probable | Solution |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop n'est pas lancé | Ouvre Docker Desktop et attends « running » |
| `port is already allocated` ou `address already in use` | Un autre programme utilise le port 5432, 8000 ou 3000 | Ferme cet autre programme (souvent un PostgreSQL déjà installé) |
| `Variable d'environnement manquante` | Le fichier `.env` n'existe pas ou est incomplet | Refais l'étape 3 |
| `ERREUR DE CONFIGURATION (fichier .env)` | Un nom a été modifié ou un mot de passe contient autre chose que des lettres et des chiffres | Corrige `.env` comme indiqué, puis `docker compose down -v` et `docker compose up --build` |
| `role ... already exists`, `database "kronops" does not exist` ou `password authentication failed` en boucle | La base a été créée avec une ancienne version de `.env` | `docker compose down -v` puis `docker compose up --build` |
| Après un `git pull`, l'écran ne change pas, même avec `Ctrl + F5` | Sous Windows et Mac, Docker Desktop ne prévient pas toujours Next.js qu'un fichier a changé (limite documentée par Next.js) | `docker compose restart frontend`, attends « Ready » dans le terminal, puis recharge la page |
| Passer d'une page à l'autre prend plusieurs secondes | Le mode développement compile les pages à la demande | Lance l'écran en mode production (étape 8) |
| `relation "..." does not exist` juste après `docker compose up -d` | L'API joue encore ses migrations | Attends 30 secondes et relance la commande, ou utilise `docker compose up --build -d --wait` |
| La page affiche « Service : injoignable » | L'API n'a pas fini de démarrer | Attends 30 secondes et recharge la page |
| Tout est cassé et tu veux repartir de zéro | | `docker compose down -v` puis `docker compose up --build`. **Attention : efface toutes les données locales.** |

## Organisation du code

```
backend/            API Django
  config/           réglages et adresses (URL)
  core/             socle commun : modèle de base, contexte client, RLS, health check
  tenants/          entreprises, sites, utilisateurs, rôles, connexion
  audit/            journal d'audit en insertion seule, et son API de lecture
  events/           table d'événements (outbox)
  catalog/          référentiels : articles, allergènes, conversions d'unités, fournisseurs et clients
  lots/             lots, mouvements (insertion seule), généalogie, recherche amont et aval
frontend/           écrans Next.js (accueil, référentiels, journal d'audit, traçabilité) et modèles CSV dans public/modeles/
docker/             script de création des rôles PostgreSQL
scripts/test.sh     lance les tests
CLAUDE.md           règles à respecter par l'assistant IA
```

## Avant le premier client payant

Ce socle a été écrit avec une IA et testé automatiquement, mais **il n'a pas été relu par un développeur professionnel**. Avant de stocker les données réelles d'un client, fais faire un audit de code et de sécurité, en priorité sur : la Row-Level Security, la connexion, le journal d'audit, et la configuration de production (`DJANGO_DEBUG=0`, HTTPS, sauvegardes). L'hébergement reste à choisir au regard de la loi ivoirienne 2013-450 (transfert de données hors du pays soumis à autorisation de l'ARTCI).
