# Accounts Receivable SQL reports

The AR queries are grouped by operational purpose. Each family contains a
README and a read-only schema inventory that should be run before a report is
first configured in a new Insights environment.

| Family | Purpose | Main queries |
| --- | --- | --- |
| [Aging](aging/README.md) | Dashboard totals for four non-overlapping aging buckets | `0-30Days.sql`, `31-60Days.sql`, `61-90Days.sql`, `91+Days.sql` |
| [Activity](activity/README.md) | Current or recent TBRACCD transaction activity | `Current_month_activity.sql`, `Current_month_payment_activity.sql`, `Current_month_loan_activity.sql` |
| [Refunds](refunds/README.md) | Refund decision support and allocation diagnostics | `Refunds.sql`, `Refund_allocation_diagnostic.sql` |
| [Contact information](contact_information/README.md) | Preferred university email and primary phone lookup | `OS_Checks.sql` |
| [Sponsors](sponsors/README.md) | Sponsored-student contracts and student/sponsor balances | `sponsored_student_summary.sql` |
| [Loans](loans/README.md) | Students grouped by Summer enrollment band with selected institutional-loan activity | `all_enrollment_load_categories_institutional_loans_summer.sql` plus three category-specific reports |

## Shared operating principles

- These are read-only reports. They do not update Banner.
- Run the family's `validate_*_schema.sql` query before relying on a report in a
  new Insights database or after an Ellucian schema change.
- Preserve existing output columns, parameter names, and financial signs when
  editing a report; saved Insights questions and operational exports may depend
  on them.
- Validate financial totals against the applicable Banner form before a new or
  changed query becomes operational.
- Do not export or commit production student data to this repository.

The aging queries use Insights/Metabase template tags (`{{...}}` and `[[...]]`).
The other report families are native PostgreSQL-flavored SQL unless their README
states otherwise.
