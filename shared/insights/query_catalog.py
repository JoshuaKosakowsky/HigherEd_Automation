"""Explicit standalone reports available in the Insights GUI query picker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.insights.banner_activity import BannerActivityParameters, BannerDetailCodeParameters

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
    requires_activity_parameters: bool = False
    administrator_only: bool = False
    result_count_column: str | None = None
    allowed_term_suffixes: tuple[str, ...] = ()
    default_detail_codes: tuple[str, ...] = ()

    @property
    def sql_path(self) -> Path:
        return REPO_ROOT / "query" / self.relative_path

    def render_sql(
        self, term_code: str | None = None, *,
        activity: BannerActivityParameters | None = None,
        detail_codes: BannerDetailCodeParameters | None = None,
    ) -> str:
        """Render only the explicitly supported, validated report parameters."""
        sql = self.sql_path.read_text(encoding="utf-8")
        if self.default_detail_codes:
            if detail_codes is None or activity is not None or term_code is not None:
                raise ValueError("Enter detail codes for this all-date report.")
            return detail_codes.render_sql(sql)
        if detail_codes is not None:
            raise ValueError("This query does not take an all-date detail-code selection.")
        if self.requires_activity_parameters:
            if activity is None or term_code is not None:
                raise ValueError("Enter feed dates and detail codes for this report.")
            return activity.render_sql(sql)
        if activity is not None:
            raise ValueError("This query does not take feed dates or detail codes.")
        if self.term_variable is None:
            if term_code is not None:
                raise ValueError("This query does not take a term.")
            return sql
        term = (term_code or "").strip()
        if len(term) != 6 or not term.isascii() or not term.isdecimal():
            raise ValueError("Enter a six-digit Banner term code.")
        if self.fall_term_only and not term.endswith("80"):
            raise ValueError("Enter a Fall Banner term ending in 80.")
        if self.allowed_term_suffixes and term[-2:] not in self.allowed_term_suffixes:
            raise ValueError("Enter a Spring (10), Summer (55), or Fall (80) Banner term.")
        marker = "{{" + self.term_variable + "}}"
        if marker not in sql or "[[" in sql:
            raise ValueError("This query's term template is not supported.")
        rendered = sql.replace(marker, f"'{term}'")
        if "{{" in rendered or "}}" in rendered:
            raise ValueError("This query has an unsupported template parameter.")
        return rendered


QUERIES: tuple[InsightsQuery, ...] = (
    InsightsQuery(
        "collections_student_profile", "Holds", "Collections demographic and academic profile",
        "AR/holds/collections_student_profile.sql",
        "All historical CO holds with an active flag and academic context for the term "
        "containing each hold's start date. Includes age, current race/sex/gender codes, "
        "term-effective majors/level, credits, prior academic standing and reconstructed GPA/class. "
        "Separate Admissions (FGA) and FAFSA (FGF) first-generation indicators; "
        "missing information stays Unknown. Later term outcomes are labeled.",
        administrator_only=True, result_count_column="Report Row Count",
    ),
    InsightsQuery(
        "wf_mines_balance_transactions", "Activity", "W&F - Mines Balance Recon transactions",
        "AR/activity/wf_mines_balance_transactions.sql",
        "All-date transaction source for the future W&F - Mines Balance Recon. "
        "Defaults to WOFF and BDRC; replace codes as needed. "
        "Includes transactions with no feed date. No hold or positive-balance filter.",
        administrator_only=True, result_count_column="Report Row Count",
        default_detail_codes=("WOFF", "BDRC"),
    ),
    InsightsQuery(
        "collections_tracking", "Holds", "W&F - Banner Recon",
        "AR/holds/collections_tracking.sql",
        "CO holds ending after today; one row per account using the latest from date. "
        "Includes separate CO/TO holds, all-term account balance, signed WOFF/BDRC Amount totals "
        "and Total Balance (account + WOFF + BDRC). "
        "Blank balances require review; feed date is not agency referral date.",
        administrator_only=True, result_count_column="Report Row Count",
    ),
    InsightsQuery(
        "rh_delinquency", "Holds", "RH delinquency review",
        "AR/holds/rh_delinquency.sql",
        "All students with RH in the account delinquency field, including former students. "
        "No date cutoff: account activity does not establish when RH was assigned. "
        "Account activity is included as context for manual Banner review.",
        administrator_only=True, result_count_column="Report Row Count",
    ),
    InsightsQuery(
        "payments_without_charges", "Term corrections", "Payments in a term with no charges",
        "AR/term_corrections/payments_without_charges.sql",
        "Enter the payment's posted term (for example 202655 for Summer). "
        "Available cash-payment credits where no charge transaction ever posted; "
        "review candidates only, with no automatic destination term or correction.",
        term_variable="payment_term", administrator_only=True,
        result_count_column="Report Row Count",
    ),
    InsightsQuery(
        "banner_activity", "Activity", "Banner Activity by Date & Detail Code",
        "AR/activity/tgiaccd_transactions.sql",
        "Transactions for selected detail codes and inclusive start/end feed dates. "
        "Enter actual dates for a period, quarter, year, or multiple years.",
        requires_activity_parameters=True,
    ),
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
        "contact_lookup", "Contact", "Student contact information",
        "AR/contact_information/student_preferred_contacts.sql",
        "Students with account-record activity in the last eight years, with active Mines (UNIV) email "
        "and PR phone, falling back to CELL. Preference flags are not required. "
        "Requires both contacts and their types. "
        "Account updates indicate recency, not formal active status. "
        "This does not identify outstanding checks.",
    ),
    InsightsQuery(
        "refund_check_contacts", "Contact", "Refund check contacts for AP matching",
        "AR/contact_information/refund_check_contacts.sql",
        "RFND/RFDP accounts with feed dates from 200 days ago through today. "
        "Student contacts for RFND; each borrower suffix and latest borrower contacts for RFDP. "
        "Missing contacts and differing borrower records are flagged. "
        "Match to AP's outstanding-check list to identify the actual payee and uncashed checks.",
        administrator_only=True, result_count_column="Report Row Count",
    ),
    InsightsQuery(
        "loan_all_enrollment", "Institutional loans", "Recent graduate and leaver review",
        "AR/loans/institutional_loan_exit_review.sql",
        "Historical institutional-loan recipients with graduation/withdrawal in the last "
        "365 days or a recent possible stop-out; enrollment is evaluated for the input term. "
        "Summer absence never establishes a stop-out. Review before sending to the loan company.",
        term_variable="target_term",
        result_count_column="__loan_row_count",
        allowed_term_suffixes=("10", "55", "80"),
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
        "deliquent_student_accounts", "Holds", "Delinquent student accounts",
        "AR/holds/deliquent_student_accounts.sql",
        "Balances and contacts for delinquency outreach review. Excludes any CO hold; "
        "includes PP accounts with an active Hold indicator. Review PP accounts "
        "in Transact before deciding whether to send outreach.",
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
