# Mini projet — pipeline de transactions (CSV → SQLite)

Pipeline locale : génération de CSV de transactions financières, validation,
agrégats, insertion atomique et idempotente dans SQLite.
Contraintes respectées : `sqlite3` de la stdlib, **pas de pandas**, seules
dépendances `pytest` et `mypy`, toutes les fonctions annotées, montants en `Decimal`.

## Installation

Python ≥ 3.11.

```bash
git clone <url-du-depot> && cd mini-projet-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # installe le paquet + pytest + mypy
```

## Commandes

| Action | Commande |
|---|---|
| Pipeline complète (génère les CSV dans `data/`, crée `pipeline.db`, insère) | `python -m txpipe` (ou `txpipe`) |
| Choisir dossier / base | `python -m txpipe --data-dir data --db pipeline.db` |
| Traiter des CSV existants sans les régénérer | `python -m txpipe --no-generate --data-dir mon_dossier` |
| Générer seulement les CSV | `python -m txpipe.generate data` |
| Tests | `pytest` |
| Typage | `mypy src/ tests/` |
| Préambule sqlite3 | `python preambule.py` |

Code de retour : `0` si tous les fichiers sont traités ou déjà traités, `1` si au moins
un fichier a échoué (les autres fichiers sont quand même traités).

## Organisation

```
src/txpipe/
  models.py      Transaction (TypedDict), colonnes CSV, InvalidFileError
  generate.py    étape 1 : CSV reproductibles (valeurs en dur)
  loading.py     étape 2 : lecture + validation (I/O et parsing)
  processing.py  étape 2 : fonctions PURES (sommes, drapeau > 5000)
  db.py          étape 3 : schéma, transaction atomique, insert_file, idempotence
  retry.py       étape 7 : retry des seules erreurs transitoires
  pipeline.py    étape 4 : orchestration + code de retour
tests/           unitaires (sans fichier), intégration, échec, retry
demo/            démonstrations pour le README (échec pipeline, mypy vs tests)
preambule.py     exercices sqlite3 du préambule
```

Chargement et traitement sont séparés : `processing.py` ne lit aucun fichier, ne fait
aucun `print` et ne modifie pas ses arguments (testé). Ses tests construisent leurs
données en mémoire.

## Schéma de la base

```sql
fichiers(id PK, nom, sha256 UNIQUE, nb_transactions, traite_le)

transactions(id PK, fichier_id → fichiers, ligne, datetime_transaction,
             iban_origine, pays_source, banque_source,
             iban_destinataire, pays_destinataire,
             montant_centimes INTEGER CHECK (> 0), devise,
             depasse_seuil INTEGER CHECK (IN (0,1)),
             UNIQUE (fichier_id, ligne))

total_envoye_par_iban   (fichier_id → fichiers, iban,   total_centimes, PK (fichier_id, iban))
total_envoye_par_banque (fichier_id → fichiers, banque, total_centimes, PK (fichier_id, banque))
total_recu_par_iban     (fichier_id → fichiers, iban,   total_centimes, PK (fichier_id, iban))
```

- Les montants sont en **centimes entiers** : pas d'erreur de représentation, et les
  `SUM` SQL restent exacts. En Python ils sont des `Decimal` ; `to_cents` refuse toute
  fraction de centime.
- Les agrégats sont stockés **par fichier** ; les totaux tous fichiers confondus
  s'obtiennent par `SELECT iban, SUM(total_centimes) … GROUP BY iban` (c'est ce que
  vérifie le test d'intégration).
- Les clés étrangères sont activées sur chaque connexion (`PRAGMA foreign_keys = ON`).

## Gestion des lignes invalides : rejet global

Une ligne est invalide si : montant non numérique, négatif, nul ou avec plus de
2 décimales ; colonne manquante ou en trop ; date illisible ; IBAN, pays ou devise mal
formés. L'en-tête doit être exactement celui attendu, et un fichier sans aucune
transaction est refusé.

**Stratégie : si une seule ligne est invalide, tout le fichier est rejeté** et rien
n'est inséré. Toutes les erreurs du fichier sont collectées (avec leur numéro de ligne)
avant le rejet, pour tout corriger en une fois. Ce choix est cohérent avec l'insertion
atomique par fichier de l'étape 3 : l'unité de traitement est le fichier, et il est
traité entièrement ou pas du tout. Il évite aussi des totaux silencieusement faux
(une ligne ignorée fausse un agrégat sans que personne ne s'en aperçoive).
Les autres fichiers du dossier continuent d'être traités ; le code de retour est `1`.

## Idempotence

Chaque fichier est identifié par le **SHA-256 de son contenu** (octets bruts), stocké dans
`fichiers.sha256` avec une contrainte `UNIQUE`. L'insertion utilise
`INSERT … ON CONFLICT (sha256) DO NOTHING` dans la même transaction que les lignes :

- même nom, contenu différent → hash différent → traité (nouvelle entrée) ;
- même contenu sous deux noms → même hash → ignoré (`SKIP`, avec le nom d'origine) ;
- relance / retry de toute la pipeline → tout est ignoré, aucun doublon.

L'unicité est garantie par la base elle-même, donc aussi en cas de retry ou de deux
exécutions concurrentes (pas de « vérifier puis insérer » vulnérable à une course). Le
fichier est lu **une seule fois** : le hash et l'analyse portent sur les mêmes octets.
Limite assumée : deux fichiers de même contenu mais avec des fins de ligne différentes
(`\n` / `\r\n`) ont des hash différents.

## Étape 6 — comportement en cas d'échec

Échec provoqué : `demo/bad_data/` contient un bon fichier et un fichier dont un montant
est « douze mille ». Reproduire :

```bash
python -m txpipe --no-generate --data-dir demo/bad_data --db /tmp/demo.db; echo "code de retour: $?"
```

Sortie réelle :

```
OK    a_ok.csv: 2 transaction(s) insérée(s) (sha256 0c9e4cd62271…)
FAIL  b_montant_non_numerique.csv: 1 erreur(s) de validation
        - ligne 3: montant invalide 'douze mille' (attendu : nombre positif, 2 décimales max)
Bilan : 1 inséré(s), 0 ignoré(s), 1 en échec
code de retour: 1
```

Les tests de `tests/test_pipeline_failure.py` vérifient : code de retour non nul (en appel
direct et via la ligne de commande), fichier fautif absent de `fichiers`, **aucune ligne**
du fichier en échec dans `transactions`, et — pour une panne en plein milieu de
l'insertion (2 lignes déjà écrites) — que le `ROLLBACK` laisse toutes les tables vides.

### Une erreur vue par mypy mais pas par les tests

`demo/mypy_demo.py` : `apply_fee` accepte un taux `float`, or `Decimal * float` lève
`TypeError` à l'exécution. Le test n'exerce que la branche sans frais : il passe.

```
$ pytest demo/ -q
.                                                                        [100%]
1 passed in 0.01s

$ mypy demo/mypy_demo.py
demo/mypy_demo.py:15: error: Unsupported operand types for * ("Decimal" and "float")  [operator]
Found 1 error in 1 file (checked 1 source file)
```

**Ce que cela apprend.** Un test ne vérifie que les chemins d'exécution qu'on lui fait
parcourir, avec les valeurs qu'on a choisies : la branche `fee_rate is not None` n'a jamais
tourné, donc le bug est invisible. mypy raisonne sur *tous* les chemins à partir des
types, sans rien exécuter : il garantit la cohérence des types partout, mais ne dit rien
de la justesse des valeurs. À l'inverse, un test attrape ce que mypy ne peut pas voir
(mauvais opérateur `>=` au lieu de `>`, seuil faux, total mal calculé : `5000.00` ne doit
pas être signalé, `5000.01` si, ce que testent `test_processing.py` et l'intégration). Les
deux sont complémentaires : mypy pour la forme et l'exhaustivité, les tests pour le
comportement.

## Étape 7 — retry : quelles erreurs, lesquelles non ?

**À réessayer : `sqlite3.OperationalError` de verrouillage** (« database is locked »,
codes `SQLITE_BUSY` / `SQLITE_LOCKED`). Elle ne dit rien sur les données, seulement sur
l'état *momentané* de la base : un autre processus tient le verrou d'écriture. Quelques
instants plus tard le verrou est libéré et la même opération peut réussir.

**À ne jamais réessayer : `sqlite3.IntegrityError`** (UNIQUE, NOT NULL, CHECK, clé
étrangère violés), ainsi que `ProgrammingError`, `OperationalError` « no such table »,
`ValueError`… Ces erreurs sont **déterministes** : elles viennent des données ou du code.
Avec les mêmes entrées, la base répondra la même chose à chaque tentative : réessayer
gaspille du temps et masque le vrai problème (il faut corriger la donnée ou le code).

Ce qui distingue les deux familles : *la cause est-elle l'état transitoire de
l'environnement (réessayer peut aider) ou la nature de la requête et des données
(réessayer ne changera rien) ?*

Implémentation (`src/txpipe/retry.py`) : `is_retryable` n'accepte que les
`OperationalError` de verrouillage ; `retry` fait au plus 3 tentatives avec attente
exponentielle (0,1 s, 0,2 s) et relève immédiatement toute autre exception. Réessayer est
sans danger parce que `insert_file` est atomique : un échec ne laisse rien en base, et en
cas de doute l'idempotence par hash empêche tout doublon. La transaction commence par
`BEGIN IMMEDIATE`, donc un verrou est détecté avant toute écriture.

Tests (`tests/test_retry.py`) : classification des erreurs, backoff, abandon après N essais,
`IntegrityError` jamais réessayée (1 seul appel), erreur transitoire simulée puis
réinsertion qui aboutit, et un **vrai verrou SQLite** (une connexion tient
`BEGIN IMMEDIATE`, le verrou saute pendant l'attente du retry, l'insertion aboutit).

## Bonus réalisés

- CI GitHub Actions (`.github/workflows/ci.yml`) : `mypy src/ tests/` et `pytest` à chaque
  push, Python 3.11 / 3.12 / 3.13.
- Agrégats consolidés tous fichiers confondus (requêtes `GROUP BY` sur les tables d'agrégats).
- Multi-devises : non géré, mais **refusé explicitement** — additionner des devises
  différentes lève `ValueError` (testé) au lieu de produire un total faux.

Non faits : PostgreSQL, S3/MinIO, `ruff`, logging structuré.

## Préambule sqlite3

`python preambule.py` rejoue les 8 exercices et affiche les réponses (dans un dossier
temporaire). Points notables : `with sqlite3.connect()` **ne ferme pas** la connexion
(il commit/rollback) → utiliser `contextlib.closing` ; sans `commit`, les données
disparaissent à la fermeture ; les clés étrangères sont **désactivées par défaut** et à
activer sur chaque connexion ; `execute()` refuse les instructions multiples mais
`executescript()` exécuterait le `DROP TABLE` d'une injection → toujours des paramètres `?`.
