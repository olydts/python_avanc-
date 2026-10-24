"""Préambule : prise en main de sqlite3 (exercices non notés).

Lancer : python preambule.py
Chaque exercice affiche ce qu'il observe ; les réponses aux questions sont dans
les commentaires et dans les affichages. Tout se passe dans un dossier temporaire.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def titre(texte: str) -> None:
    print(f"\n=== {texte} ===")


def nb_clients(db: Path) -> int:
    with closing(sqlite3.connect(db)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0])


def ex1_connexions(db: Path) -> None:
    titre("1. Connexion, with, :memory:")
    conn = sqlite3.connect(db)
    conn.close()
    print("connect() puis close() : ouverture/fermeture explicites")

    with sqlite3.connect(db) as conn:
        conn.execute("SELECT 1")
    try:
        conn.execute("SELECT 1")
        print("ATTENTION : après un 'with', la connexion est TOUJOURS ouverte.")
        print("  'with' ne fait que COMMIT (ou ROLLBACK si exception), il ne ferme pas.")
    finally:
        conn.close()

    with closing(sqlite3.connect(db)) as conn:  # la bonne façon de fermer
        conn.execute("SELECT 1")
    print("closing(...) ferme réellement la connexion à la sortie du bloc")

    # :memory: -> base temporaire, détruite à la fermeture, propre à chaque connexion.
    with closing(sqlite3.connect(":memory:")) as m1, closing(sqlite3.connect(":memory:")) as m2:
        m1.execute("CREATE TABLE t (x INTEGER)")
        try:
            m2.execute("SELECT * FROM t")
        except sqlite3.OperationalError as exc:
            print(f":memory: change tout : aucun fichier, une base distincte par connexion ({exc})")


def ex2_create_table(db: Path) -> None:
    titre("2. CREATE TABLE deux fois")
    ddl = "CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, pays TEXT NOT NULL)"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(ddl)
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError as exc:
            print(f"2e exécution -> OperationalError : {exc}")
        conn.execute(ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS"))
        print("Avec CREATE TABLE IF NOT EXISTS : aucune erreur, la relance est idempotente")


def ex3_insertions(db: Path) -> None:
    titre("3. Insertions, executemany, commit oublié")
    with closing(sqlite3.connect(db)) as conn:
        for nom, pays in [("Alice", "FR"), ("Bruno", "DE"), ("Chloé", "FR")]:
            conn.execute("INSERT INTO clients (nom, pays) VALUES (?, ?)", (nom, pays))
        conn.executemany(
            "INSERT INTO clients (nom, pays) VALUES (?, ?)",
            [("Dina", "ES"), ("Emil", "DE"), ("Farah", "FR")],
        )
        conn.commit()
    print(f"après commit + fermeture + réouverture : {nb_clients(db)} clients")

    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO clients (nom, pays) VALUES (?, ?)", ("Oublié", "FR"))
        # pas de commit : la fermeture annule la transaction en cours
    print(f"insertion SANS commit puis fermeture : {nb_clients(db)} clients -> la ligne est perdue")


def ex4_group_by(db: Path) -> None:
    titre("4. COUNT par pays, row_factory")
    sql = "SELECT pays, COUNT(*) AS nb FROM clients GROUP BY pays ORDER BY pays"
    with closing(sqlite3.connect(db)) as conn:
        for row in conn.execute(sql):
            print("par index  :", row[0], row[1])
        conn.row_factory = sqlite3.Row
        for row in conn.execute(sql):
            print("par nom    :", row["pays"], row["nb"])


def ex5_injection() -> None:
    titre("5. Paramètre ? contre f-string (injection SQL)")
    malveillant = "Robert'); DROP TABLE clients;--"

    def base() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT)")
        conn.execute("INSERT INTO clients (nom) VALUES ('Alice')")
        return conn

    with closing(base()) as conn:
        conn.execute("INSERT INTO clients (nom) VALUES (?)", (malveillant,))
        nom = conn.execute("SELECT nom FROM clients ORDER BY id DESC").fetchone()[0]
        print(f"avec ?        : la chaîne est stockée telle quelle -> {nom!r}")

    with closing(base()) as conn:
        try:
            conn.execute(f"INSERT INTO clients (nom) VALUES ('{malveillant}')")
        except sqlite3.Error as exc:
            print(f"f-string + execute()      : refusé ({type(exc).__name__}: {exc})")
            print("  -> execute() n'accepte qu'UNE instruction : protection accidentelle, pas une défense.")

    with closing(base()) as conn:
        conn.executescript(f"INSERT INTO clients (nom) VALUES ('{malveillant}');")
        tables = conn.execute("SELECT name FROM sqlite_master WHERE name = 'clients'").fetchall()
        print(f"f-string + executescript() : table clients encore là ? {bool(tables)} -> DROP exécuté !")

    with closing(base()) as conn:
        astuce = "' OR '1'='1"
        fuite = conn.execute(f"SELECT COUNT(*) FROM clients WHERE nom = '{astuce}'").fetchone()[0]
        sain = conn.execute("SELECT COUNT(*) FROM clients WHERE nom = ?", (astuce,)).fetchone()[0]
        print(f"injection en une seule instruction : f-string renvoie {fuite} ligne(s), avec ? : {sain}")


def ex6_cles_etrangeres(db: Path) -> None:
    titre("6. Clé étrangère")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS commandes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "client_id INTEGER NOT NULL REFERENCES clients(id), "
            "montant_centimes INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO commandes (client_id, montant_centimes) VALUES (999, 100)")
        conn.commit()
        print("client 999 inexistant : l'insertion PASSE.")
        print("  Pourquoi ? SQLite ignore les clés étrangères par défaut (PRAGMA foreign_keys = OFF),")
        print("  réglage à refaire sur CHAQUE connexion.")
        conn.execute("DELETE FROM commandes")
        conn.commit()

        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("INSERT INTO commandes (client_id, montant_centimes) VALUES (999, 100)")
        except sqlite3.IntegrityError as exc:
            print(f"avec PRAGMA foreign_keys = ON -> IntegrityError : {exc}")


def ex7_rollback(db: Path) -> None:
    titre("7. Transaction + rollback")
    avant = nb_clients(db)
    with closing(sqlite3.connect(db)) as conn:
        try:
            conn.execute("INSERT INTO clients (nom, pays) VALUES (?, ?)", ("Gaël", "FR"))
            conn.execute("INSERT INTO clients (nom, pays) VALUES (?, ?)", (None, "FR"))  # NOT NULL
        except sqlite3.IntegrityError as exc:
            print(f"2e insertion refusée : {exc} -> rollback")
            conn.rollback()
    apres = nb_clients(db)
    print(f"clients avant : {avant}, après : {apres} -> la 1re insertion n'est pas en base non plus")


def ex8_unique(db: Path) -> None:
    titre("8. Contrainte UNIQUE")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE utilisateurs (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
        conn.execute("INSERT INTO utilisateurs (email) VALUES ('a@b.fr')")
        try:
            conn.execute("INSERT INTO utilisateurs (email) VALUES ('a@b.fr')")
        except sqlite3.Error as exc:
            print(f"type exact : {type(exc).__module__}.{type(exc).__name__}")
            print(f"message    : {exc}")
            print(f"code       : {getattr(exc, 'sqlite_errorname', '?')}")
            print(f"hiérarchie : {[c.__name__ for c in type(exc).__mro__[:4]]}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "essai.db"
        ex1_connexions(db)
        ex2_create_table(db)
        ex3_insertions(db)
        ex4_group_by(db)
        ex5_injection()
        ex6_cles_etrangeres(db)
        ex7_rollback(db)
        ex8_unique(db)


if __name__ == "__main__":
    main()
