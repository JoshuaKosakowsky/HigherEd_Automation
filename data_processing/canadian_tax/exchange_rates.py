"""Published Bank of Canada annual averages and their audit provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode

import requests


RATE_SERIES = "FXAUSDCAD"
RATE_PAGE = "https://www.bankofcanada.ca/rates/exchange/annual-average-exchange-rates/"
RATE_API = "https://www.bankofcanada.ca/valet/observations/group/FX_RATES_ANNUAL/json"
CRA_GUIDANCE = (
    "https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/"
    "about-your-tax-return/tax-return/completing-a-tax-return/deductions-credits-expenses/"
    "line-32300-your-tuition-education-textbook-amounts/recognized-educational-institutions-outside-canada/"
    "info-educational-institutions-outside-canada.html"
)


def parse_annual_rate(payload: dict, tax_year: int) -> Decimal | None:
    """Never substitute a daily, monthly, partial-year or other-year rate."""
    observations = payload.get("observations")
    if not isinstance(observations, list) or any(not isinstance(row, dict) for row in observations):
        raise ValueError("Bank of Canada response is missing observations.")
    matched = [row for row in observations if row.get("d") == f"{tax_year}-01-01"]
    if not matched:
        return None
    if len(matched) != 1:
        raise ValueError("Bank of Canada response has duplicate annual observations.")
    try:
        rate = Decimal(matched[0][RATE_SERIES]["v"])
    except (KeyError, TypeError, InvalidOperation):
        raise ValueError("Bank of Canada annual USD/CAD observation is invalid.") from None
    if not rate.is_finite() or rate <= 0:
        raise ValueError("Bank of Canada annual USD/CAD rate must be finite and positive.")
    return rate


def fetch_annual_rate(tax_year: int) -> tuple[dict, dict | None]:
    """Only the year is sent externally; retain the public response for audit."""
    params = {"start_date": f"{tax_year}-01-01", "end_date": f"{tax_year}-12-31"}
    metadata = {
        "method": "Bank of Canada published annual average",
        "rate_year": tax_year, "series": RATE_SERIES,
        "direction": "CAD per 1 USD", "source_url": RATE_PAGE,
        "api_url": RATE_API + "?" + urlencode(params),
        "guidance_url": CRA_GUIDANCE,
        "conversion_formula": "eligible paid USD * CAD per 1 USD; round final CAD to cents",
        "applicability": "For fees paid throughout the year. Cross-year payments require review of the appropriate payment-year rate before conversion.",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        response = requests.get(RATE_API, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Bank of Canada returned an invalid response.")
        rate = parse_annual_rate(payload, tax_year)
    except (requests.RequestException, ValueError):
        metadata.update(status="unavailable", cad_per_usd=None)
        return metadata, None
    metadata.update(
        status="published" if rate is not None else "not_published",
        cad_per_usd=str(rate) if rate is not None else None,
        observation_date=f"{tax_year}-01-01" if rate is not None else None,
        api_url=response.url,
    )
    return metadata, payload


def convert_usd_to_cad(amount_usd: Decimal, cad_per_usd: Decimal) -> Decimal:
    if not amount_usd.is_finite() or not cad_per_usd.is_finite() or cad_per_usd <= 0:
        raise ValueError("Conversion requires a finite amount and positive rate.")
    return (amount_usd * cad_per_usd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
