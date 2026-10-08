#!/usr/bin/env python3
"""Append an enriched FPL CSV to the main electric CSV.

The main CSV controls the output column order. Rows already present in the
main file are skipped by default using sha256 when available, with a
normalized account/meter/billing-period key as a fallback.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path


NATURAL_KEY_FIELDS = ("accountNumber", "meterNumber", "periodStart", "periodEnd")


def clean(value: str | None) -> str:
    return (value or "").strip()


def normalize_date(value: str | None) -> str:
    """Normalize common date formats so equivalent dates compare equally."""
    value = clean(value)
    if not value:
        return ""
    value = re.sub(r"\s+0:00:00?$", "", value)
    value = re.sub(r"\s+00:00:00?$", "", value)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value.lower()


def natural_key(row: dict[str, str]) -> tuple[str, ...]:
    values = [clean(row.get("accountNumber")), clean(row.get("meterNumber"))]
    values.extend(normalize_date(row.get(field)) for field in NATURAL_KEY_FIELDS[2:])
    return tuple(value.lower() for value in values)


def row_keys(row: dict[str, str]) -> set[tuple[str, ...]]:
    """Return one or two identities for a row, when available."""
    keys: set[tuple[str, ...]] = set()
    sha256 = clean(row.get("sha256")).lower()
    if sha256:
        keys.add(("sha256", sha256))
    natural = natural_key(row)
    if all(natural):
        keys.add(("natural", *natural))
    return keys


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        return list(reader.fieldnames), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows({name: row.get(name, "") for name in fieldnames} for row in rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def combine(
    source_path: Path,
    main_path: Path,
    output_path: Path,
    dedupe: bool,
    source_dataset: str,
) -> tuple[int, int, int]:
    source_fields, source_rows = read_csv(source_path)
    main_fields, main_rows = read_csv(main_path)

    # Preserve main_electric's schema and append any unexpected source fields.
    output_fields = list(main_fields)
    output_fields.extend(field for field in source_fields if field not in output_fields)

    identities: set[tuple[str, ...]] = set()
    if dedupe:
        for row in main_rows:
            identities.update(row_keys(row))

    appended = 0
    skipped = 0
    for source_row in source_rows:
        keys = row_keys(source_row)
        if dedupe and keys and identities.intersection(keys):
            skipped += 1
            continue

        output_row = {field: source_row.get(field, "") for field in output_fields}
        if "sourceDataset" in output_fields and not clean(output_row.get("sourceDataset")):
            output_row["sourceDataset"] = source_dataset
        main_rows.append(output_row)
        identities.update(keys)
        appended += 1

    write_csv(output_path, output_fields, main_rows)
    return len(source_rows), appended, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="CSV to append, such as fpl_selected_bills_enriched.csv")
    parser.add_argument("main", type=Path, help="Existing main CSV, such as main_electric_csv.csv")
    parser.add_argument("-o", "--output", type=Path, help="Output CSV path")
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Append every source row, including rows already in the main CSV",
    )
    parser.add_argument(
        "--source-dataset",
        default="fpl_selected_bills_enriched",
        help="Value for sourceDataset on appended rows when that column exists",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or args.main.with_name(f"{args.main.stem}_combined{args.main.suffix}")
    total, appended, skipped = combine(
        args.source,
        args.main,
        output,
        dedupe=not args.no_dedupe,
        source_dataset=args.source_dataset,
    )
    print(f"Wrote: {output}")
    print(f"Source rows: {total}")
    print(f"Rows appended: {appended}")
    print(f"Rows skipped as duplicates: {skipped}")


if __name__ == "__main__":
    main()
