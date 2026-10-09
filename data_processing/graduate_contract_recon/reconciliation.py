"""Exact-cent document matching and student attribution for account 1305."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .sources import Issue, SourceData, Transaction, ZERO, fiscal_scope, prepare_source
from shared.insights.banner_activity import BannerActivityParameters


DOC_HEADERS = ["Fiscal Year", "Period", "Quarter", "Feed Document", "Workday Debit", "Banner Debit",
    "Debit Difference", "Workday Credit", "Banner Credit", "Credit Difference", "Workday Row Count",
    "Banner Row Count", "Status", "Notes", "Review Status"]
CWID_HEADERS = ["Fiscal Year", "Period", "Quarter", "CWID", "Banner Debit", "Banner Credit",
    "Other Workday Debit", "Other Workday Credit", "Debits", "Credits", "Net Period Activity",
    "Banner Row Count", "Other Workday Row Count", "Review Status", "Notes / Explanation"]
COMBINED_HEADERS = ["Fiscal Year", "Period", "Quarter", "Memo / Feed Document", "Source", "Source Row",
    "Date", "CWID", "Account ID", "Journal Entry", "Detail Code", "Term", "Description / Original Memo",
    "Debit", "Credit", "Included in Activity", "Activity Debit", "Activity Credit", "Status", "Transaction User"]
PERIOD_HEADERS = ["Fiscal Year", "Period", "Quarter", "Workday SIS Debit", "Banner Debit",
    "Debit Difference", "Workday SIS Credit", "Banner Credit", "Credit Difference",
    "Other Workday Debit", "Other Workday Credit", "Combined Activity Debit", "Combined Activity Credit",
    "Workday minus Combined Debit", "Workday minus Combined Credit", "Document Exceptions", "Status"]


@dataclass(frozen=True)
class Reconciliation:
    parameters: BannerActivityParameters
    sources: tuple[SourceData, SourceData]
    documents: list[list[object]]
    students: list[list[object]]
    combined: list[list[object]]
    periods: list[list[object]]
    verification: list[list[object]]
    issues: list[Issue]


def total(rows: list[Transaction], side: str) -> Decimal:
    return sum((getattr(row, side) for row in rows), ZERO)


def reconcile(
    workday: SourceData, banner: SourceData, parameters: BannerActivityParameters,
) -> Reconciliation:
    wd, wd_issues = prepare_source(workday, parameters)
    bn, bn_issues = prepare_source(banner, parameters)
    issues = wd_issues + bn_issues
    # Invalid selected rows can otherwise leave a partial group that happens to
    # agree. Duplicate identities also cannot be silently accepted or removed.
    blocked = any(issue.issue.startswith(("Invalid", "Duplicate")) for issue in issues)
    groups = defaultdict(lambda: {"Workday": [], "Banner": []})
    non_sis = [row for row in wd if row.kind.upper() != "SIS"]
    for row in wd + bn:
        if row.feed and (row.source == "Banner" or row.kind.upper() == "SIS"):
            groups[row.group_key][row.source].append(row)
    feed_periods = defaultdict(set)
    for year, period, feed in groups:
        feed_periods[feed].add((year, period))
    timing = {feed for feed, scopes in feed_periods.items() if len(scopes) > 1}
    for feed in sorted(timing):
        issues.append(Issue("Both", 0, f"Feed {feed} appears in multiple fiscal periods; timing or reused-reference review required"))
    documents, statuses = [], {}
    for key, sides in sorted(groups.items()):
        year, period, feed = key
        wr, br = sides["Workday"], sides["Banner"]
        wdebit, wcredit = total(wr, "debit"), total(wr, "credit")
        bdebit, bcredit = total(br, "debit"), total(br, "credit")
        if not wr:
            status = "Missing Workday"
        elif not br:
            status = "Missing Banner"
        elif wdebit != bdebit or wcredit != bcredit:
            status = "Amount difference"
        elif feed in timing:
            status = "Timing / reused reference review"
        elif blocked or any(row.concerns for row in wr):
            status = "Source review required"
        else:
            status = "Amounts agree"
        statuses[key] = status
        quarter = f"Q{(int(period[1:]) - 1) // 3 + 1}"
        documents.append([f"FY{year}", period, quarter, feed, wdebit, bdebit, wdebit - bdebit,
            wcredit, bcredit, wcredit - bcredit, len(wr), len(br), status, "", "Not reviewed"])

    # Display Workday summaries above their Banner detail, but count only one
    # source in activity totals when the amounts agree.
    combined = []
    ordered = []
    displayed_groups = set()
    for row in wd:
        if row.kind.upper() == "SIS" and row.feed:
            if row.group_key in displayed_groups:
                continue
            displayed_groups.add(row.group_key)
            ordered.extend(groups[row.group_key]["Workday"])
            ordered.extend(groups[row.group_key]["Banner"])
        else:
            ordered.append(row)
    ordered.extend(row for row in bn if row.group_key not in displayed_groups)
    for row in ordered:
        status = statuses.get(row.group_key, "Missing feed document")
        if row.source == "Workday":
            included = not (row.kind.upper() == "SIS" and status == "Amounts agree")
            if row.kind.upper() != "SIS":
                status = "Other Workday activity"
        else:
            included = status == "Amounts agree"
        if row.concerns:
            status += "; " + "; ".join(row.concerns)
        year, period, quarter = fiscal_scope(row.day)
        combined.append([f"FY{year}", period, quarter, row.feed or row.memo, row.source, row.row,
            row.day, row.cwid, row.account, row.journal, row.code, row.term, row.memo,
            row.debit, row.credit, "Yes" if included else
                "Summary reference" if row.source == "Workday" else "Review only",
            row.debit if included else ZERO, row.credit if included else ZERO, status, row.user])

    by_student = defaultdict(list)
    for row in bn + non_sis:
        if row.cwid:
            year, period, _ = fiscal_scope(row.day)
            by_student[year, period, row.cwid].append(row)
    students = []
    for (year, period, cwid), rows in sorted(by_student.items()):
        br = [row for row in rows if row.source == "Banner"]
        other = [row for row in rows if row.source == "Workday"]
        debit, credit = total(rows, "debit"), total(rows, "credit")
        follow_up = blocked or any(row.concerns or (row.source == "Banner" and statuses.get(row.group_key) != "Amounts agree") for row in rows)
        students.append([f"FY{year}", period, f"Q{(int(period[1:]) - 1) // 3 + 1}", cwid,
            total(br, "debit"), total(br, "credit"), total(other, "debit"), total(other, "credit"),
            debit, credit, debit - credit, len(br), len(other),
            "Follow-up needed" if follow_up else "Not reviewed", ""])

    periods = []
    current = parameters.start_date.replace(day=1)
    while current <= parameters.end_date:
        year, period, quarter = fiscal_scope(current)
        wr = [row for row in wd if fiscal_scope(row.day)[:2] == (year, period)]
        br = [row for row in bn if fiscal_scope(row.day)[:2] == (year, period)]
        sis = [row for row in wr if row.kind.upper() == "SIS"]
        other = [row for row in wr if row.kind.upper() != "SIS"]
        cb = [row for row in combined if row[:2] == [f"FY{year}", period]]
        cdebit = sum((row[16] for row in cb), ZERO)
        ccredit = sum((row[17] for row in cb), ZERO)
        bad = sum(value != "Amounts agree" for key, value in statuses.items() if key[:2] == (year, period))
        status = ("No supplied activity" if not wr and not br else
                  "Review required" if bad or issues or not wr or not br else "Supplied activity agrees")
        periods.append([f"FY{year}", period, quarter, total(sis, "debit"), total(br, "debit"),
            total(sis, "debit") - total(br, "debit"), total(sis, "credit"), total(br, "credit"),
            total(sis, "credit") - total(br, "credit"), total(other, "debit"), total(other, "credit"),
            cdebit, ccredit, total(wr, "debit") - cdebit, total(wr, "credit") - ccredit, bad, status])
        if current.year == parameters.end_date.year and current.month == parameters.end_date.month:
            break
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)

    sis = [row for row in wd if row.kind.upper() == "SIS"]
    student_debit = sum((row[8] for row in students), ZERO)
    student_credit = sum((row[9] for row in students), ZERO)
    cdebit = sum((row[16] for row in combined), ZERO)
    ccredit = sum((row[17] for row in combined), ZERO)
    bad_count = sum(status != "Amounts agree" for status in statuses.values())
    attribution_debit = total(bn + non_sis, "debit") - student_debit
    attribution_credit = total(bn + non_sis, "credit") - student_credit
    agrees = bool(wd and bn and not issues and not bad_count and
        not attribution_debit and not attribution_credit and
        total(sis, "debit") == total(bn, "debit") and total(sis, "credit") == total(bn, "credit"))
    verification = [
        ["Conclusion", "Supplied selected activity agrees; upload completeness unconfirmed" if agrees else "OPEN: review source coverage, exceptions and differences"],
        ["Selected start (inclusive)", parameters.start_date], ["Selected end (inclusive)", parameters.end_date],
        ["Selected detail codes", ", ".join(parameters.detail_codes)],
        ["Ledger account", "1305 Graduate Contract Receivable"],
        ["Calendar", "July–June; July P01; fiscal quarters; no adjusting period inferred"],
        ["Workday source", workday.label], ["Banner source", banner.label],
        ["Workday selected rows", len(wd)], ["Banner selected rows", len(bn)],
        ["Workday selected date span", f"{min(row.day for row in wd)} to {max(row.day for row in wd)}" if wd else "No selected rows"],
        ["Banner selected date span", f"{min(row.day for row in bn)} to {max(row.day for row in bn)}" if bn else "No selected rows"],
        ["Banner duplicate identity check", "Available: account/transaction identity" if "transaction" in banner.columns else "Not available: extract omits transaction number; duplicate rows are retained"],
        ["Workday SIS debit", total(sis, "debit")], ["Banner debit", total(bn, "debit")],
        ["SIS debit difference", total(sis, "debit") - total(bn, "debit")],
        ["Workday SIS credit", total(sis, "credit")], ["Banner credit", total(bn, "credit")],
        ["SIS credit difference", total(sis, "credit") - total(bn, "credit")],
        ["Document groups missing/different/requiring review", bad_count],
        ["Source warnings / invalid rows", len(issues)],
        ["Combined activity debit", cdebit], ["Combined activity credit", ccredit],
        ["Workday debit minus combined activity debit", total(wd, "debit") - cdebit],
        ["Workday credit minus combined activity credit", total(wd, "credit") - ccredit],
        ["Banner + non-SIS Workday debit minus CWID debit", attribution_debit],
        ["Banner + non-SIS Workday credit minus CWID credit", attribution_credit],
        ["Combined interpretation", "Activity Debit/Credit count matched Banner detail and retained Workday once. Other Banner rows are review only."],
        ["Student interpretation", "Banner plus non-SIS Workday activity by CWID; no Workday SIS allocation is inferred. Net period activity is not an ending balance."],
        ["Coverage", "Date selection and agreeing totals cannot prove an upload contains all source rows. Validate exports against source-system controls."],
        ["Memo matching", "Workday SIS External Reference (fallback Memo) to Banner Feed Document, within the same fiscal year/period; exact cents on debit AND credit."],
        ["Review notes", "New workbook each run; prior reviewer notes are not automatically carried forward."],
        ["Refresh", "Calculated snapshot: rerun the automation after changing inputs, dates or codes. Editing source tabs does not recalculate the outputs."],
    ]
    return Reconciliation(parameters, (workday, banner), documents, students, combined, periods, verification, issues)
