"""Étape 1 : génération de fichiers CSV de transactions (jeu de données reproductible).

Les valeurs sont écrites en dur : deux exécutions produisent exactement les mêmes
octets, ce qui rend les traitements de l'étape 2 réellement testables.
"""

from __future__ import annotations

from pathlib import Path

from txpipe.models import CSV_COLUMNS

# (iban, pays, banque)
Origin = tuple[str, str, str]
# (iban, pays)
Dest = tuple[str, str]
# (datetime ISO, origine, destinataire, montant)
Row = tuple[str, Origin, Dest, str]

_A: Origin = ("FR7630006000011234567890189", "FR", "BNPPARIBAS")
_B: Origin = ("FR1420041010050500013M02606", "FR", "SOCGEN")
_C: Origin = ("FR7630004000031234567890143", "FR", "BNPPARIBAS")
_D: Origin = ("DE02120300000000202051", "DE", "DKB")

_DE: Dest = ("DE89370400440532013000", "DE")
_ES: Dest = ("ES9121000418450200051332", "ES")
_GB: Dest = ("GB29NWBK60161331926819", "GB")
_IT: Dest = ("IT60X0542811101000000123456", "IT")
_NL: Dest = ("NL91ABNA0417164300", "NL")

CURRENCY = "EUR"

SAMPLE_FILES: dict[str, list[Row]] = {
    "transactions_2024-03-01.csv": [
        ("2024-03-01T09:12:00", _A, _DE, "1250.00"),
        ("2024-03-01T10:45:00", _A, _ES, "7400.50"),  # > 5000
        ("2024-03-01T11:30:00", _B, _GB, "320.75"),
        ("2024-03-01T14:05:00", _C, _IT, "5000.00"),  # pile 5000 : PAS au-dessus
        ("2024-03-01T15:20:00", _A, _NL, "89.90"),
        ("2024-03-01T16:48:00", _B, _DE, "6100.00"),  # > 5000
    ],
    "transactions_2024-03-02.csv": [
        ("2024-03-02T08:30:00", _C, _ES, "450.00"),
        ("2024-03-02T09:50:00", _D, _GB, "12000.00"),  # > 5000
        ("2024-03-02T13:15:00", _A, _IT, "2300.40"),
        ("2024-03-02T17:05:00", _B, _NL, "5000.01"),  # > 5000 d'un centime
        ("2024-03-02T18:22:00", _D, _DE, "75.00"),
    ],
    "transactions_2024-03-03.csv": [
        ("2024-03-03T09:00:00", _A, _DE, "410.00"),
        ("2024-03-03T10:10:00", _C, _ES, "5200.00"),  # > 5000
        ("2024-03-03T11:40:00", _D, _NL, "33.33"),
        ("2024-03-03T12:15:00", _B, _IT, "980.10"),
        ("2024-03-03T13:55:00", _A, _GB, "15000.00"),  # > 5000
        ("2024-03-03T15:30:00", _C, _DE, "640.00"),
        ("2024-03-03T16:00:00", _D, _IT, "1999.99"),
    ],
}


def _format_row(row: Row) -> str:
    when, (iban_o, pays_o, banque), (iban_d, pays_d), montant = row
    return ",".join((when, iban_o, pays_o, banque, iban_d, pays_d, montant, CURRENCY))


def render_csv(rows: list[Row]) -> str:
    """Construit le contenu texte d'un fichier CSV (en-tête + transactions)."""
    lines = [",".join(CSV_COLUMNS), *(_format_row(r) for r in rows)]
    return "\n".join(lines) + "\n"


def generate_csv_files(out_dir: Path) -> list[Path]:
    """Écrit les fichiers CSV dans `out_dir` (créé au besoin) et renvoie leurs chemins."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, rows in SAMPLE_FILES.items():
        path = out_dir / name
        path.write_text(render_csv(rows), encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def main() -> None:
    """`python -m txpipe.generate [dossier]` : génère seulement les CSV."""
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    for path in generate_csv_files(target):
        print(path)


if __name__ == "__main__":
    main()
