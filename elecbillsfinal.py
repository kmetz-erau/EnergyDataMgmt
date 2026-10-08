import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell
def _():
    import csv
    import io
    import re
    from datetime import datetime

    import marimo as mo
    import requests

    return csv, datetime, io, mo, re, requests


@app.cell
def _(mo):
    source_upload = mo.ui.file(
        filetypes=[".csv"],
        multiple=False,
        kind="area",
        label="Upload fpl_selected_bills_enriched.csv",
    )

    main_upload = mo.ui.file(
        filetypes=[".csv"],
        multiple=False,
        kind="area",
        label="Optional: upload the existing main electric CSV",
    )

    dedupe = mo.ui.checkbox(
        value=True,
        label="Skip duplicate rows",
    )

    mapped_only = mo.ui.checkbox(
        value=False,
        label="Keep only accounts found in the mapping CSV",
    )

    run_button = mo.ui.run_button(
        label="Combine and map CSV files",
        kind="success",
    )

    mo.vstack(
        [
            mo.md("## FPL Electric Data Combiner"),
            mo.md(
                "Upload the enriched FPL CSV. The account mapping is "
                "loaded automatically from GitHub."
            ),
            source_upload,
            main_upload,
            mo.hstack([dedupe, mapped_only]),
            run_button,
        ],
        gap=1,
    )
    return dedupe, main_upload, mapped_only, run_button, source_upload


@app.cell
def _(csv, datetime, io, re):
    MAPPING_URL = (
        "https://raw.githubusercontent.com/kmetz-erau/EnergyDataMgmt/main/"
        "electric_account_mapping.csv"
    )

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

    def clean(value):
        return (value or "").strip()

    def account_key(value):
        value = clean(value)
        return value.lstrip("0") or "0"

    def normalize_date(value):
        value = clean(value)

        if not value:
            return ""

        value = re.sub(r"\s+0:00:00?$", "", value)
        value = re.sub(r"\s+00:00:00?$", "", value)

        for fmt in (
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M",
            "%Y-%m-%d %H:%M",
        ):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass

        return value.lower()

    def row_keys(row):
        keys = set()

        sha256 = clean(row.get("sha256")).lower()

        if sha256:
            keys.add(("sha256", sha256))

        natural = (
            clean(row.get("accountNumber")).lower(),
            clean(row.get("meterNumber")).lower(),
            normalize_date(row.get("periodStart")),
            normalize_date(row.get("periodEnd")),
        )

        if all(natural):
            keys.add(("natural", *natural))

        return keys

    def parse_csv(data):
        reader = csv.DictReader(
            io.StringIO(data.decode("utf-8-sig"))
        )

        if not reader.fieldnames:
            raise ValueError(
                "The uploaded file has no header row."
            )

        return list(reader.fieldnames), list(reader)

    return CHILLER_LOOP_ACCOUNTS, MAPPING_URL, account_key, parse_csv, row_keys


@app.cell
def _(CHILLER_LOOP_ACCOUNTS, account_key, csv, io, parse_csv, row_keys):
    def append_source(source_data, main_data, dedupe):
        source_fields, source_rows = parse_csv(source_data)

        if main_data:
            main_fields, main_rows = parse_csv(main_data)
        else:
            main_fields, main_rows = source_fields, []

        fields = list(main_fields)

        fields.extend(
            field
            for field in source_fields
            if field not in fields
        )

        identities = set()

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

            row = {
                field: source_row.get(field, "")
                for field in fields
            }

            if (
                "sourceDataset" in fields
                and not row.get("sourceDataset", "").strip()
            ):
                row["sourceDataset"] = (
                    "fpl_selected_bills_enriched"
                )

            main_rows.append(row)
            identities.update(keys)
            appended += 1

        return fields, main_rows, {
            "source_rows": len(source_rows),
            "appended": appended,
            "skipped": skipped,
        }

    def add_mapping(fields, rows, mapping_data, mapped_only):
        mapping_fields, mapping_rows = parse_csv(mapping_data)

        if "accountNumber" not in fields:
            raise ValueError(
                "The electric CSV must contain 'accountNumber'."
            )

        if "account_number" not in mapping_fields:
            raise ValueError(
                "The mapping CSV must contain 'account_number'."
            )

        mapping_by_account = {}

        for mapping_row in mapping_rows:
            key = account_key(
                mapping_row.get("account_number")
            )

            if key == "0":
                raise ValueError(
                    "The mapping CSV contains a blank account_number."
                )

            if key in mapping_by_account:
                raise ValueError(
                    f"Duplicate account_number in mapping CSV: {key}"
                )

            mapping_by_account[key] = mapping_row

        output_fields = list(fields)

        if "on_chiller_loop" not in output_fields:
            output_fields.append("on_chiller_loop")

        added_fields = []

        for field in mapping_fields:
            if field == "account_number":
                continue

            if field in output_fields:
                output_field = f"mapping_{field}"
            else:
                output_field = field

            added_fields.append((field, output_field))
            output_fields.append(output_field)

        output_rows = []
        matched = 0

        for row in rows:
            account = account_key(
                row.get("accountNumber")
            )

            mapping_row = mapping_by_account.get(account)

            if mapping_row:
                matched += 1
            elif mapped_only:
                continue

            output_row = {
                field: row.get(field, "")
                for field in fields
            }

            output_row["on_chiller_loop"] = str(
                account in CHILLER_LOOP_ACCOUNTS
            ).lower()

            for source_field, output_field in added_fields:
                if mapping_row:
                    output_row[output_field] = mapping_row.get(
                        source_field,
                        "",
                    )
                else:
                    output_row[output_field] = ""

            output_rows.append(output_row)

        unmatched = len(rows) - matched

        return (
            output_fields,
            output_rows,
            matched,
            unmatched,
        )

    def to_csv_bytes(fields, rows):
        output = io.StringIO(newline="")

        writer = csv.DictWriter(
            output,
            fieldnames=fields,
            lineterminator="\n",
        )

        writer.writeheader()

        writer.writerows(
            {
                field: row.get(field, "")
                for field in fields
            }
            for row in rows
        )

        return output.getvalue().encode("utf-8")

    return add_mapping, append_source, to_csv_bytes


@app.cell
def _(
    MAPPING_URL,
    add_mapping,
    append_source,
    dedupe,
    main_upload,
    mapped_only,
    mo,
    requests,
    run_button,
    source_upload,
    to_csv_bytes,
):
    if not run_button.value:
        result_display = mo.md(
            "Upload your file and click **Combine and map CSV files**."
        )

    elif not source_upload.value:
        result_display = mo.callout(
            mo.md(
                "Upload `fpl_selected_bills_enriched.csv` first."
            ),
            kind="warn",
        )

    else:
        try:
            source_data = source_upload.value[0].contents

            if main_upload.value:
                main_data = main_upload.value[0].contents
            else:
                main_data = None

            response = requests.get(
                MAPPING_URL,
                timeout=30,
            )
            response.raise_for_status()

            mapping_data = response.content

            fields, rows, stats = append_source(
                source_data,
                main_data,
                dedupe=dedupe.value,
            )

            fields, rows, matched, unmatched = add_mapping(
                fields,
                rows,
                mapping_data,
                mapped_only=mapped_only.value,
            )

            result = to_csv_bytes(fields, rows)

            summary = mo.md(
                f"""
    ### Processing complete

    | Metric | Count |
    |---|---:|
    | Source rows | {stats["source_rows"]} |
    | Rows appended | {stats["appended"]} |
    | Duplicates skipped | {stats["skipped"]} |
    | Accounts matched | {matched} |
    | Accounts unmatched | {unmatched} |
    | Rows written | {len(rows)} |
    """
            )

            download = mo.download(
                data=result,
                filename="final_electric_combined.csv",
                mimetype="text/csv",
                label="⬇️ Download final_electric_combined.csv",
            )

            result_display = mo.vstack(
                [
                    summary,
                    download,
                ]
            )

        except Exception as exc:
            result_display = mo.callout(
                mo.md(f"**Could not process the files:** {exc}"),
                kind="danger",
            )

    result_display
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
