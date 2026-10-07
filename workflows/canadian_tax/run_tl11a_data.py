"""Prepare one student's reconciled TL11A review; no certificate is issued."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from app.gui import APP_VERSION
from data_processing.canadian_tax.exchange_rates import fetch_annual_rate
from data_processing.canadian_tax.preparation import (
    DEFAULT_RULES, QUERY_DIRECTORY, REPOSITORY_ROOT, load_rules,
    validate_inputs,
)
from data_processing.canadian_tax.pipeline import extract_data, prepare_review, read_source_package, review_metadata, write_package
from shared.insights.config import load_department_profiles
from shared.insights.session_auth import build_authenticated_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwid", help="One student account; never printed to logs.")
    parser.add_argument("--tax-year", type=int)
    parser.add_argument("--environment", choices=["TEST", "PROD"], default="TEST")
    parser.add_argument("--schema-only", action="store_true", help="Inspect metadata without querying students.")
    parser.add_argument("--output-dir", type=Path, help="New directory; existing directories are never replaced.")
    parser.add_argument("--rules-file", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--source-package", type=Path, help="Rebuild a review from a complete downloaded ZIP without Insights sign-in.")
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if arguments.source_package and (arguments.schema_only or arguments.cwid or arguments.tax_year is not None):
        parser.error("--source-package reads its account/year from the ZIP; do not combine it with student/schema arguments.")
    if not arguments.schema_only and not arguments.source_package:
        if not arguments.cwid or arguments.tax_year is None:
            parser.error("--cwid and --tax-year are required unless --schema-only is used.")
        validate_inputs(arguments.cwid, arguments.tax_year)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    label = "schema" if arguments.schema_only else str(arguments.tax_year)
    output = arguments.output_dir or REPOSITORY_ROOT / "data/canadian_tax" / f"tl11a_{label}_{timestamp}"
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory.")
    rules = load_rules(arguments.rules_file)
    if arguments.source_package:
        frames, manifest = read_source_package(arguments.source_package)
        manifest["source_app_version"] = manifest.get("app_version")
        manifest["app_version"] = APP_VERSION
        review = prepare_review(frames, manifest, rules)
        write_package(output, frames, manifest, review)
        print(f"TL11A review saved: {output / 'tl11a_review.xlsx'}")
        return 0
    load_dotenv(REPOSITORY_ROOT / ".env")
    profile = load_department_profiles()[arguments.environment]
    if profile is None:
        raise ValueError("Selected Insights environment is not configured.")
    print(f"Preparing TL11A data in {arguments.environment}.")
    client, _ = build_authenticated_client(
        profile.settings, browser="chrome", experience_url=profile.experience_url,
    )
    with client:
        schema = client.run_sql_file(QUERY_DIRECTORY / "validate_canadian_tax_schema.sql")
        inventory = client.run_sql_file(QUERY_DIRECTORY / "payment_application_inventory.sql")
        if schema.empty or "validation_status" not in schema:
            raise ValueError("Schema inventory did not return the expected results.")
        missing = schema["validation_status"].ne("FOUND").sum()
        frames = {"schema": schema, "payment_application_columns": inventory}
        if not arguments.schema_only:
            if missing:
                raise ValueError("Required Banner columns are missing. Run --schema-only and review schema.csv.")
            frames.update(extract_data(client, arguments.cwid, arguments.tax_year))
    manifest = {
        "app_version": APP_VERSION, "environment": arguments.environment,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema_missing_columns": int(missing),
        "status": "schema_inventory" if arguments.schema_only else "data_preparation_only",
    }
    review = None
    if not arguments.schema_only:
        print("Fetching the published Bank of Canada annual USD/CAD rate.")
        rate, response = fetch_annual_rate(arguments.tax_year)
        manifest.update(review_metadata(arguments.cwid, arguments.tax_year, arguments.environment, APP_VERSION, rate, response))
        review = prepare_review(frames, manifest, rules)
    write_package(output, frames, manifest, review)
    print(f"Data package saved. Required schema columns missing: {missing}.")
    if not arguments.schema_only:
        print(f"Annual exchange rate status: {manifest['exchange_rate']['status']}. Amount status: {manifest['status']}.")
        print(f"Review workbook: {output / 'tl11a_review.xlsx'}")
    print(f"Output directory: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"TL11A: {error}")
        raise SystemExit(1) from None
    except Exception:
        # Outer operational/auth boundary: no SQL, student rows or raw API/auth
        # exception details in terminal logs.
        print("TL11A data preparation failed. Check Insights access and the output location; no certificate was prepared.")
        raise SystemExit(1) from None
