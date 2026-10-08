#!/usr/bin/env python3
"""Add building/account mapping fields to a main electric CSV."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path


# Hardcoded from the `CW = 1` rows on the workbook's `FPL KWH` sheet.
# Account numbers are stored without leading-zero padding for comparison.
CHILLER_LOOP_ACCOUNTS = {
    "8920081067",
    "2489797155",
    "2583088048",
    "866970577",
    "9937144179",
    "923485197",
    "7649590390",
    "2175708953",
    "4140510407",
    "597947423",
    "8281789027",
    "204486419",
    "6817708222",
    "4728351455",
    "7272148268",
    "698563160",
    "5954141163",
    "4092027129",
    "696189380",
    "1258168226",
    "4001977240",
    "7287874197",
    "970126587",
    "5138663108",
    "5566426028",
    "3117707905",
    "1966352104",
    "4916435573",
    "6141586534",
    "7352160357",
    "748842101",
    "9890440572",
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        return list(reader.fieldnames), list(reader)


def account_key(value: str | None) -> str:
    """Compare account numbers as identifiers, ignoring whitespace and padding zeros."""
    value = (value or "").strip()
    return value.lstrip("0") or "0"


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


def map_accounts(
    main_path: Path,
    mapping_path: Path,
    output_path: Path,
    mapped_only: bool = False,
) -> tuple[int, int, int]:
    main_fields, main_rows = read_csv(main_path)
    mapping_fields, mapping_rows = read_csv(mapping_path)

    required_main = "accountNumber"
    required_mapping = "account_number"
    if required_main not in main_fields:
        raise ValueError(f"{main_path} must contain a '{required_main}' column")
    if required_mapping not in mapping_fields:
        raise ValueError(f"{mapping_path} must contain a '{required_mapping}' column")

    mapping_by_account: dict[str, dict[str, str]] = {}
    for row in mapping_rows:
        key = account_key(row.get(required_mapping))
        if not key or key == "0":
            raise ValueError("Mapping file contains a blank account_number")
        if key in mapping_by_account:
            raise ValueError(f"Mapping file contains duplicate account_number: {row[required_mapping]}")
        mapping_by_account[key] = row

    # Avoid overwriting main-electric columns. account_number is the join key;
    # the other mapping fields are added with a mapping_ prefix when needed.
    added_fields: list[tuple[str, str]] = []
    output_fields = list(main_fields)
    chiller_field = "on_chiller_loop"
    if chiller_field not in output_fields:
        output_fields.append(chiller_field)
    for field in mapping_fields:
        if field == required_mapping:
            continue
        output_field = field if field not in output_fields else f"mapping_{field}"
        added_fields.append((field, output_field))
        output_fields.append(output_field)

    output_rows: list[dict[str, str]] = []
    matched = 0
    for main_row in main_rows:
        mapping_row = mapping_by_account.get(account_key(main_row.get(required_main)))
        if mapping_row:
            matched += 1
        elif mapped_only:
            continue

        output_row = {field: main_row.get(field, "") for field in main_fields}
        output_row[chiller_field] = str(
            account_key(main_row.get(required_main)) in CHILLER_LOOP_ACCOUNTS
        ).lower()
        for source_field, output_field in added_fields:
            output_row[output_field] = mapping_row.get(source_field, "") if mapping_row else ""
        output_rows.append(output_row)

    write_csv(output_path, output_fields, output_rows)
    return len(main_rows), matched, len(main_rows) - matched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("main", type=Path, help="Main electric CSV")
    parser.add_argument("mapping", type=Path, help="Account-to-building mapping CSV")
    parser.add_argument("-o", "--output", type=Path, help="Output CSV path")
    parser.add_argument(
        "--mapped-only",
        action="store_true",
        help="Drop electric rows whose account is not in the mapping file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or args.main.with_name(f"{args.main.stem}_mapped{args.main.suffix}")
    total, matched, unmatched = map_accounts(
        args.main, args.mapping, output, mapped_only=args.mapped_only
    )
    print(f"Wrote: {output}")
    print(f"Main rows: {total}")
    print(f"Matched rows: {matched}")
    print(f"Unmatched rows: {unmatched}")


if __name__ == "__main__":
    main()
