"""Shared preparation and offline package validation for TL11A review."""

from __future__ import annotations

import io
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import pandas as pd

from .calculation import calculate_review, TuitionReview
from .preparation import (
    prepare_enrollment, prepare_payment_applications, prepare_transactions,
    summarize_codes, validate_extract, validate_inputs, render_query,
)
from shared.cancellation import CancellationToken
from shared.insights.client import InsightsClient
from shared.progress import ProgressReporter


SOURCE_NAMES = ("identity", "transactions", "enrollment", "programs", "payment_applications")


def review_metadata(cwid: str, tax_year: int, environment: str, app_version: str,
                    rate: dict, response: dict | None) -> dict:
    """Audit metadata shared by live GUI and CLI runs; never store CWID in logs."""
    return {
        "app_version": app_version, "environment": environment, "tax_year": tax_year,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(), "schema_missing_columns": 0,
        "exchange_rate": rate, "bank_of_canada_response": response,
        "query_hashes": {name: hashlib.sha256(render_query(name, cwid, tax_year).encode()).hexdigest()
                         for name in SOURCE_NAMES},
        "enrollment_policy": {
            "minimum_consecutive_days": 21, "duration_convention": "Scheduled start and end dates are inclusive.",
            "summer_policy": "Summer counts; no full-time credit-hour threshold is inferred from duration.",
        },
    }


def extract_data(client: InsightsClient, cwid: str, tax_year: int, *,
                 cancellation: CancellationToken | None = None,
                 progress: ProgressReporter | None = None) -> dict[str, pd.DataFrame]:
    validate_inputs(cwid, tax_year)
    frames = {}
    for name in SOURCE_NAMES:
        if cancellation:
            cancellation.check()
        if progress:
            progress.report(f"Reading TL11A {name.replace('_', ' ')}")
        frame = client.run_sql(render_query(name, cwid, tax_year))
        validate_extract(frame, tax_year)
        if name == "identity" and len(frame) != 1:
            raise ValueError("CWID did not resolve to exactly one current identity.")
        if not frame.empty and not frame["pidm"].eq(frames.get("identity", frame).iloc[0]["pidm"]).all():
            raise ValueError("Extract account does not match the selected identity.")
        frames[name] = frame
    if frames["enrollment"].duplicated(["pidm", "term_code", "crn"]).any():
        raise ValueError("Registration rows are duplicated; reconcile section/part-of-term joins.")
    if cancellation:
        cancellation.check()
    return frames


def write_package(output: Path, frames: dict[str, pd.DataFrame], manifest: dict,
                  review: TuitionReview | None = None) -> None:
    """Create exclusively and remove only this run's partial output on failure."""
    from .export import export_review

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    try:
        for name, frame in frames.items():
            frame.to_csv(output / f"{name}.csv", index=False)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if review is not None:
            export_review(review, frames, manifest, output / "tl11a_review.xlsx")
    except Exception:
        shutil.rmtree(output)
        raise


def prepare_review(frames: dict[str, pd.DataFrame], manifest: dict, rules: dict) -> TuitionReview:
    """Rebuild derived tables from complete raw extracts and a captured policy/rate."""
    tax_year = manifest["tax_year"]
    for name in SOURCE_NAMES:
        validate_extract(frames[name], tax_year)
    identity = frames["identity"]
    if len(identity) != 1:
        raise ValueError("Package must identify exactly one current student.")
    for name in SOURCE_NAMES:
        if not frames[name].empty and not frames[name].pidm.astype(str).eq(str(identity.iloc[0].pidm)).all():
            raise ValueError("Package contains extracts from different accounts.")
    if frames["enrollment"].duplicated(["pidm", "term_code", "crn"]).any():
        raise ValueError("Registration rows are duplicated; reconcile source joins.")
    frames["transactions_prepared"] = prepare_transactions(frames["transactions"], rules)
    frames["payment_applications_prepared"] = prepare_payment_applications(
        frames["payment_applications"], frames["transactions_prepared"],
    )
    frames["enrollment_prepared"] = prepare_enrollment(frames["enrollment"])
    frames["detail_code_review"] = summarize_codes(frames["transactions_prepared"])
    review = calculate_review(
        frames["transactions_prepared"], frames["payment_applications_prepared"],
        frames["enrollment_prepared"], frames["programs"], tax_year,
        manifest["exchange_rate"], manifest.get("bank_of_canada_response"),
    )
    frames.update(tuition_charges=review.charges, application_calculation=review.applications,
                  transaction_reconciliation=review.reconciliation, sessions=review.sessions,
                  review_checks=review.checks)
    manifest.update(
        status="review_amounts" if review.paid_cad is not None else "amount_review_required",
        eligible_paid_usd=str(review.paid_usd) if review.paid_usd is not None else None,
        eligible_paid_cad=str(review.paid_cad) if review.paid_cad is not None else None,
        certificate_status="Pending administrator confirmation; no certificate generated",
        detail_code_rules=rules, row_counts={name: len(frame) for name, frame in frames.items()},
        calculation_policy={
            "funding": "Positive P-to-C allocations include scholarships; C-to-C credits are not payments.",
            "reapplications": "Omit Y rows only after validating equal reverse-direction pairs.",
            "reconciliation": "Every full-history transaction must reconcile amount minus stored balance to directed application flows.",
            "calendar_scope": "Requested-year candidate charges with verified enrolled sessions; no automatic cross-year session proration.",
            "cad_rounding": "Round the final USD total times the annual CAD-per-USD rate to cents, half up.",
        },
        review_required=review.checks.loc[review.checks.result.ne("OK"), "detail"].tolist() + [
            "Sequential Insights extracts reflect warehouse data, not a guaranteed atomic/live Banner snapshot.",
        ],
    )
    return review


def read_source_package(path: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    """Read a ZIP without extracting paths; ignore stale prepared CSVs."""
    with ZipFile(path) as archive:
        def read(name: str) -> bytes:
            matches = [item for item in archive.infolist() if not item.is_dir() and Path(item.filename).name == name]
            if len(matches) != 1:
                raise ValueError("Source package has missing or duplicate required files.")
            return archive.read(matches[0])

        manifest = json.loads(read("manifest.json"))
        if type(manifest.get("tax_year")) is not int or not 2000 <= manifest["tax_year"] <= 2099:
            raise ValueError("Package tax year is invalid.")
        frames = {}
        for name in SOURCE_NAMES + ("schema", "payment_application_columns"):
            frame = pd.read_csv(io.BytesIO(read(name + ".csv")), dtype=str)
            for column in ("extract_row_count", "extract_tax_year"):
                if column in frame:
                    frame[column] = pd.to_numeric(frame[column], errors="raise")
            frames[name] = frame
        if frames["schema"].empty or frames["schema"].validation_status.ne("FOUND").any():
            raise ValueError("Source package has unresolved required schema columns.")
        manifest["source_package"] = path.name
        return frames, manifest
