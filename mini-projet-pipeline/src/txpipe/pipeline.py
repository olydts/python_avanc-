"""Étape 4 : la pipeline complète derrière une seule commande.

    python -m txpipe [--data-dir data] [--db pipeline.db] [--no-generate]

Code de retour : 0 si tous les fichiers sont traités (ou déjà traités), 1 si au
moins un fichier a échoué. Un fichier en échec n'empêche pas les autres d'être traités.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from txpipe.db import connect, init_db, insert_file
from txpipe.generate import generate_csv_files
from txpipe.loading import load_file
from txpipe.models import InvalidFileError
from txpipe.retry import retry


def _out(message: str) -> None:
    print(message, flush=True)


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run_pipeline(data_dir: Path, db_path: Path, *, generate: bool = True) -> int:
    """Génération -> chargement -> traitement -> insertion. Renvoie le code de retour."""
    if generate:
        generated = generate_csv_files(data_dir)
        _out(f"Génération : {len(generated)} fichier(s) CSV dans {data_dir}")

    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        _err(f"FAIL  aucun fichier CSV trouvé dans {data_dir}")
        return 1

    try:
        conn = connect(db_path)
        init_db(conn)
    except sqlite3.Error as exc:
        _err(f"FAIL  impossible d'ouvrir la base {db_path} : {exc}")
        return 1

    inserted = skipped = failed = 0
    with closing(conn):
        for path in csv_files:
            try:
                digest, transactions = load_file(path)
                result = retry(lambda: insert_file(conn, path.name, digest, transactions))
            except InvalidFileError as exc:
                failed += 1
                _err(f"FAIL  {path.name}: {exc}")
                for error in exc.errors:
                    _err(f"        - {error}")
            except Exception as exc:  # frontière : un fichier en échec n'arrête pas les autres
                failed += 1
                _err(f"FAIL  {path.name}: {type(exc).__name__}: {exc}")
            else:
                if result.inserted:
                    inserted += 1
                    _out(
                        f"OK    {path.name}: {result.nb_transactions} transaction(s) "
                        f"insérée(s) (sha256 {digest[:12]}…)"
                    )
                else:
                    skipped += 1
                    _out(
                        f"SKIP  {path.name}: déjà traité "
                        f"(même contenu que {result.existing_name!r})"
                    )

    _out(f"Bilan : {inserted} inséré(s), {skipped} ignoré(s), {failed} en échec")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="txpipe", description="Pipeline CSV de transactions -> SQLite"
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--db", type=Path, default=Path("pipeline.db"))
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="ne pas (re)générer les CSV : traiter ceux déjà présents dans --data-dir",
    )
    args = parser.parse_args(argv)
    return run_pipeline(args.data_dir, args.db, generate=not args.no_generate)


if __name__ == "__main__":
    sys.exit(main())
