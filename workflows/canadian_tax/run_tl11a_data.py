"""Prepare one student's TL11A source data; no final certificate calculation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
from dotenv import load_dotenv

from app.gui import APP_VERSION
from data_processing.canadian_tax.exchange_rates import fetch_annual_rate
from data_processing.canadian_tax.preparation import (
    DEFAULT_RULES, QUERY_DIRECTORY, REPOSITORY_ROOT, load_rules,
    prepare_enrollment, prepare_payment_applications, prepare_transactions,
    render_query, summarize_codes, validate_extract, validate_inputs,
)
from shared.insights.client import InsightsClient
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
    return parser


def extract_data(client: InsightsClient, cwid: str, tax_year: int) -> dict[str, pd.DataFrame]:
    validate_inputs(cwid, tax_year)
    frames = {}
    for name in ("identity", "transactions", "enrollment", "programs", "payment_applications"):
        frame = client.run_sql(render_query(name, cwid, tax_year))
        validate_extract(frame, tax_year)
        if name == "identity" and len(frame) != 1:
            raise ValueError("CWID did not resolve to exactly one current identity.")
        if not frame.empty and not frame["pidm"].eq(frames.get("identity", frame).iloc[0]["pidm"]).all():
            raise ValueError("Extract account does not match the selected identity.")
        frames[name] = frame
    if frames["enrollment"].duplicated(["pidm", "term_code", "crn"]).any():
        raise ValueError("Registration rows are duplicated; reconcile section/part-of-term joins.")
    return frames


def write_package(output: Path, frames: dict[str, pd.DataFrame], manifest: dict) -> None:
    """Create exclusively and remove this run's partial output on a write failure."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Must not replace another student's or an earlier run's package.
    try:
        for name, frame in frames.items():
            frame.to_csv(output / f"{name}.csv", index=False)
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        # Intentional cleanup boundary; delete only the directory created above.
        shutil.rmtree(output)
        raise


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if not arguments.schema_only:
        if not arguments.cwid or arguments.tax_year is None:
            parser.error("--cwid and --tax-year are required unless --schema-only is used.")
        validate_inputs(arguments.cwid, arguments.tax_year)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    label = "schema" if arguments.schema_only else str(arguments.tax_year)
    output = arguments.output_dir or REPOSITORY_ROOT / "data/canadian_tax" / f"tl11a_{label}_{timestamp}"
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory.")
    rules = load_rules(arguments.rules_file)
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
    if not arguments.schema_only:
        frames["transactions_prepared"] = prepare_transactions(frames["transactions"], rules)
        frames["payment_applications_prepared"] = prepare_payment_applications(
            frames["payment_applications"], frames["transactions_prepared"],
        )
        frames["enrollment_prepared"] = prepare_enrollment(frames["enrollment"])
        frames["detail_code_review"] = summarize_codes(frames["transactions_prepared"])
        print("Fetching the published Bank of Canada annual USD/CAD rate.")
        rate, response = fetch_annual_rate(arguments.tax_year)
        manifest.update(
            tax_year=arguments.tax_year, exchange_rate=rate,
            detail_code_rules=rules,
            eligible_paid_usd=None, eligible_paid_cad=None,
            row_counts={name: len(frame) for name, frame in frames.items()},
            query_hashes={name: hashlib.sha256(render_query(name, arguments.cwid, arguments.tax_year).encode()).hexdigest()
                          for name in ("identity", "transactions", "enrollment", "programs", "payment_applications")},
            enrollment_policy={
                "minimum_consecutive_days": 21,
                "duration_convention": "Scheduled start and end dates are inclusive.",
                "summer_policy": "Report owner confirmed Summer counts; no credit-hour full-time threshold is inferred from course duration.",
            },
            review_required=[
                "Fee exclusions are FEIT/CFEE only under the report owner's policy; verify application treatment before calculating retained tuition paid.",
                "Reconcile payment application signs, direct-payment/reapplication flags, scholarships, refunds and reversals before summing applications.",
                "Reconcile program and session dates to SGASTDN/SFARSTS; confirm full-time attendance and qualifying courses.",
                "Review cross-year payments and the appropriate rate year; no transaction posting date is assumed to be payment date.",
                "Sequential Insights extracts reflect warehouse data, not a guaranteed atomic or live Banner snapshot.",
            ],
            bank_of_canada_response=response,
        )
        if frames["enrollment"].empty:
            manifest["review_required"].append("No registration rows returned for the requested year's candidate terms.")
        if frames["programs"].empty or frames["programs"].duplicated(["pidm", "term_code"]).any():
            manifest["review_required"].append("Program records are missing or tied at the latest effective term.")
        if frames["payment_applications"].empty:
            manifest["review_required"].append("No payment application records returned; do not infer paid tuition from zero balances.")
        elif frames["payment_applications_prepared"].application_review_status.ne("linked").any():
            manifest["review_required"].append("Some payment applications have missing transaction links or unexpected charge/payment types.")
        if frames["enrollment_prepared"].course_duration_status.isin(["review_dates", "below_minimum", "review_enrollment_status"]).any():
            manifest["review_required"].append("Some courses have unverified dates/enrollment or are shorter than three weeks.")
    write_package(output, frames, manifest)
    print(f"Data package saved. Required schema columns missing: {missing}.")
    if not arguments.schema_only:
        print(f"Annual exchange rate status: {manifest['exchange_rate']['status']}. Tuition paid remains pending review.")
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
