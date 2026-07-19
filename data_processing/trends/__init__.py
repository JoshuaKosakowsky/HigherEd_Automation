"""Historical Trends workbook workflow."""
from .config import TrendsConfig
from .pipeline import run_trends_pipeline


__all__ = [
    "TrendsConfig",
    "run_trends_pipeline",
]