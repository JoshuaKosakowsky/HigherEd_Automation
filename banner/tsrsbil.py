from __future__ import annotations

from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeoutError

from banner.login import login_if_needed
from data_processing.shared.files import ensure_dir
from data_processing.shared.dates import stamp_yyyymmdd, compute_future_term_code


FORM = "TSRSBIL"
EXPECTED_HEADER_PREFIX = "SSBSECT_VPDI_CODE,SSBSECT_TERM_CODE,"

LOG_PREFIX = "SOAHOLD"
FORM = "SOAHOLD"