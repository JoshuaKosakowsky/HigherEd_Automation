# Sponsored student account report

This project starts a Banner Insights report for students who have a third-party
contract/sponsor attachment in the current or immediately previous Mines term.

## Query model

- `TBBCSTU` identifies the student-to-sponsor contract attachment.
- `TBBCONT` supplies the contract description and configured student-payment and
  sponsor-charge detail codes.
- `TBRACCD` supplies transactions for both accounts.
- `TBBDETC_TYPE_IND` classifies each transaction as a charge (`C`) or
  payment/credit (`P`). The report does not maintain a local list of detail codes.
- `SPRIDEN` supplies current IDs and names.

`TBBCSTU` does **not** contain charges, payments, or balances. The summary query
rolls those values up from `TBRACCD`.

## Run order

1. Run `validate_sponsor_schema.sql` in Insights. Confirm the expected tables
   and columns below are exposed in the Insights database.
2. Run `sponsored_student_summary.sql`.
3. Validate several results against TSACONT and TSAAREV before the query is used
   operationally.

The term logic follows the repository's Mines term configuration:

- Spring: `YYYY10`, January 1 through May 15
- Summer: `YYYY55`, May 16 through July 15
- Fall: `YYYY80`, July 16 through December 31

The immediately preceding configured term is included automatically. A
`current_term_override` is available near the top of the summary query for a
controlled historical validation run.

## Required columns

The first draft relies on these key fields:

- `TBBCSTU_STU_PIDM`, `TBBCSTU_CONTRACT_PIDM`,
  `TBBCSTU_CONTRACT_NUMBER`, `TBBCSTU_CONTRACT_PRIORITY`,
  `TBBCSTU_TERM_CODE`
- `TBBCONT_PIDM`, `TBBCONT_CONTRACT_NUMBER`, `TBBCONT_TERM_CODE`
- `TBRACCD_PIDM`, `TBRACCD_TERM_CODE`, `TBRACCD_AMOUNT`,
  `TBRACCD_DETAIL_CODE`, `TBRACCD_CROSSREF_PIDM`
- `TBBDETC_DETAIL_CODE`, `TBBDETC_TYPE_IND`

## Meaning of the financial columns

Term charges and payments include all activity on that student's or sponsor's
account for the displayed term. Sponsor term totals therefore repeat when a
sponsor has multiple attached students; the column labels explicitly say
`All Students` to avoid treating those values as student-specific.

The two `Linked` amounts use `TBRACCD_CROSSREF_PIDM` in each direction. They are
intended to help identify the student credit and corresponding sponsor charge,
but local Banner posting behavior must be validated before these are treated as
the authoritative amount for one contract.

Term balance is calculated as:

```text
charges - payments
```

Full account balance uses the same accounting sign across all terms. Both are
based on `TBRACCD_AMOUNT`; the query does not sum the transaction-level
`TBRACCD_BALANCE` field.

Transactions whose detail code is missing from `TBBDETC`, or whose type is not
`C` or `P`, are excluded from calculated balances and reported in the four
unclassified-detail count columns. Any nonzero count requires review.

## First-run validation

For at least one student/sponsor pair in each displayed term:

1. Confirm the contract number, priority, authorization, and sponsor match
   TSACONT.
2. Confirm term charges and payments against TSAAREV for the student.
3. Confirm sponsor totals against TSAAREV for the sponsor account. Remember that
   these are sponsor-wide totals, not a single student's allocation.
4. Compare `Student Credits Linked to Sponsor` and
   `Sponsor Charges Linked to Student`. Investigate differences before using
   either value as a contract-specific total.
5. Determine the local values and business meaning of `TBBCSTU_DEL_IND` and
   `TBBCSTU_AUTH_IND`. The first draft displays them and does not filter them.
6. Confirm every unclassified-detail count is zero before relying on a balance.
