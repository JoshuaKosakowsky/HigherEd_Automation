"""Explicit standalone reports available in the Insights GUI query picker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class InsightsQuery:
    query_id: str
    group: str
    title: str
    relative_path: str
    description: str
    term_variable: str | None = None
    fall_term_only: bool = False

    @property
    def sql_path(self) -> Path:
        return REPO_ROOT / "query" / self.relative_path

    def render_sql(self, term_code: str | None = None) -> str:
        """Fill the one supported term tag with a validated SQL text literal."""
        sql = self.sql_path.read_text(encoding="utf-8")
        if self.term_variable is None:
            if term_code is not None:
                raise ValueError("This query does not take a term.")
            return sql
        term = (term_code or "").strip()
        if len(term) != 6 or not term.isascii() or not term.isdecimal():
            raise ValueError("Enter a six-digit Banner term code.")
        if self.fall_term_only and not term.endswith("80"):
            raise ValueError("Enter a Fall Banner term ending in 80.")
        marker = "{{" + self.term_variable + "}}"
        if marker not in sql or "[[" in sql:
            raise ValueError("This query's term template is not supported.")
        rendered = sql.replace(marker, f"'{term}'")
        if "{{" in rendered or "}}" in rendered:
            raise ValueError("This query has an unsupported template parameter.")
        return rendered


QUERIES: tuple[InsightsQuery, ...] = (
    InsightsQuery(
        "current_month_activity", "Activity", "Current month transactions",
        "AR/activity/Current_month_activity.sql",
        "All transactions with feed dates from the first of this month onward; no upper date bound.",
    ),
    InsightsQuery(
        "last_month_activity", "Activity", "Last month transactions",
        "AR/activity/Last_month_activity.sql",
        "All transactions with feed dates in the previous calendar month.",
    ),
    InsightsQuery(
        "current_month_payment", "Activity", "Current month payment activity",
        "AR/activity/Current_month_payment_activity.sql",
        "Uses the existing payment detail-code list; CFEE is labeled as a card fee.",
    ),
    InsightsQuery(
        "last_month_payment", "Activity", "Last month payment activity",
        "AR/activity/Last_month_payment_activity.sql",
        "Uses the same payment detail-code list for the previous calendar month.",
    ),
    InsightsQuery(
        "historical_loan_activity", "Activity", "Loan activity draft (prior two months)",
        "AR/activity/Current_month_loan_activity.sql",
        "Draft report: two months before this month; its detail-code list and grouping need review.",
    ),
    InsightsQuery(
        "contact_lookup", "Contact", "Active school email and primary phone",
        "AR/contact_information/OS_Checks.sql",
        "Contact lookup; despite the filename, it does not identify outstanding checks.",
    ),
    InsightsQuery(
        "loan_all_enrollment", "Institutional loans", "All enrollment load categories",
        "AR/loans/all_enrollment_load_categories_institutional_loans_summer.sql",
        "Requires a six-digit Banner term; the combined Summer enrollment report.",
        term_variable="target_term",
    ),
    InsightsQuery(
        "loan_less_than_half", "Institutional loans", "Less than half time",
        "AR/loans/less_than_half_time_institutional_loans.sql",
        "Requires a six-digit Banner term; loan activity below half-time enrollment.",
        term_variable="target_term",
    ),
    InsightsQuery(
        "loan_half_to_full", "Institutional loans", "Half time to less than full time",
        "AR/loans/half_time_less_than_full_time_institutional_loans_summer.sql",
        "Requires a six-digit Banner term; Summer half-to-full-time band.",
        term_variable="target_term",
    ),
    InsightsQuery(
        "loan_full_time", "Institutional loans", "Full time and above",
        "AR/loans/full_time_and_above_institutional_loans_summer.sql",
        "Requires a six-digit Banner term; Summer full-time-and-above band.",
        term_variable="target_term",
    ),
    InsightsQuery(
        "parent_plus", "Financial aid", "Parent PLUS sample",
        "FA/Parent_plus.sql",
        "Existing query returns up to 20 RLRPAPP rows with PLUS-to-student marked Y.",
    ),
    InsightsQuery(
        "sponsored_student_summary", "Sponsors", "Sponsored student summary",
        "AR/sponsors/sponsored_student_summary.sql",
        "Current and previous term sponsor/student account summary; reconcile before operational use.",
    ),
    InsightsQuery(
        "refund_review", "Refunds", "Refund review SQL (large)",
        "AR/refunds/Refunds.sql",
        "Full candidate review with allocation calculations. May exceed API timeout; review only, no refunds issued.",
    ),
    InsightsQuery(
        "refund_manual_transactions", "Refunds", "Manual transaction extract (large)",
        "AR/refunds/refund_transactions_manual.sql",
        "One half of the manual refund extraction pair; use with the context extract and matching settings.",
    ),
    InsightsQuery(
        "refund_manual_context", "Refunds", "Manual context extract (large)",
        "AR/refunds/refund_context_manual.sql",
        "One half of the manual refund extraction pair; use with the transaction extract and matching settings.",
    ),
    InsightsQuery(
        "term_sample", "Testing", "Banner term reference sample",
        "insights_testing/stvterm_sample.sql",
        "At most ten Banner term reference rows; useful for a low-risk export test.",
    ),
    InsightsQuery(
        "ship_should_have_health", "SHIP", "Should have HLTH",
        "SHIP/Exception_report-Fall_ShouldHave_HLTH.sql",
        "Requires a Fall term ending in 80; legacy health-insurance exception SQL.",
        term_variable="v_fall_term_code", fall_term_only=True,
    ),
    InsightsQuery(
        "ship_should_not_have_health", "SHIP", "Should not have HLTH",
        "SHIP/Exception_report-Fall_ShouldNotHave_HLTH.sql",
        "Requires a Fall term ending in 80; legacy health-insurance exception SQL.",
        term_variable="v_fall_term_code", fall_term_only=True,
    ),
)


def get_query(query_id: str) -> InsightsQuery:
    """Resolve a selected report ID; paths never come from GUI input."""
    for query in QUERIES:
        if query.query_id == query_id:
            return query
    raise ValueError("Select an available Insights query.")
