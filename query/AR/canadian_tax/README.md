# Canadian tuition certificate data (TL11A)

This report family supports one CWID and a calendar tax year. It prepares
source data for review; it does not issue a PDF or certify a tuition-paid total.
Run it using [the workflow instructions](../../../workflows/canadian_tax/README.md).

## Sources and grains

| Extract | Source | Grain / purpose |
| --- | --- | --- |
| Identity | Current `SPRIDEN` | Exactly one account |
| Transactions | `TBRACCD`, `TBBDETC`, `STVTERM` | One account transaction, including full history |
| Enrollment | `SFRSTCR`, `STVRSTS`, `SSBSECT`, `SOBPTRM` | One registration per term/CRN, including dropped rows |
| Programs | `SGBSTDN` | Latest effective program record for each candidate term; retain ties |
| Payment applications | `TBRAPPL` | One raw application record; link payment/charge transaction numbers locally |
| Payment application inventory | `information_schema.columns` | Discover visible `TBRAPPL` columns without reading student applications |

The SQL templates are executed by the Python workflow. They are not standalone
Insights questions: `tl11a_scope.sql` supplies the common scope, and the workflow
substitutes validated CWID/year literals. Do not put a real CWID into repository
SQL files. `validate_canadian_tax_schema.sql` and
`payment_application_inventory.sql` can be run directly in Insights.

Candidate terms have a code beginning with the requested year or calendar dates
overlapping it. This deliberately broad scope exposes missing dates and
cross-year terms for review. It is not a final course-year determination.
Financial history is not filtered by posting dates: prepaid or late-paid tuition
can belong to the course year. Terms are labeled using `STVTERM` descriptions.

Section dates and part-of-term dates remain separate. Compare the latter with
the part-of-term information used in SFARSTS, and compare the program code,
degree and level with SGASTDN. Dates describe schedules, not actual attendance;
credit hours alone do not prove CRA full-time attendance or qualifying courses.
Prepared enrollment checks each course for at least 21 consecutive scheduled
days, counting both start and end dates. It uses section dates, or a complete
part-of-term date pair when section dates are incomplete. Conflicting, invalid
or missing dates require review. Dropped/non-counting registrations do not pass
the duration check as enrolled courses. The report owner confirmed Summer
counts; a qualifying duration does not independently establish full-time
attendance. No full-time credit-hour threshold or certificate month total is
inferred in this step. Program labels are not derived. `SGBSTDN`
primary-program fields must first be confirmed against SGASTDN, especially for
students with multiple curricula.

## Validation before operational use

1. Run the schema inventory in TEST. Resolve each `MISSING` column and confirm
   the expected schema names. These Banner fields are proposed mappings and
   have not been verified against this tenant for this workflow.
2. Extract a permitted account and reconcile transactions to TSAAREV. Verify
   `TBBDETC_TYPE_IND` uses `C` for charge and `P` for payment and that the signed
   raw amounts match Banner. Negative amounts remain negative.
3. Reconcile registration/section/part-of-term and program data to the forms
   above. Duplicated transaction or registration keys fail extraction rather
   than multiplying amounts. Latest-effective program ties remain visible.
4. Reconcile `payment_applications.csv` and its prepared transaction links.
   Applications retain original signed amounts, identifiers, versions, direct
   payment/reapplication flags and dates, including records outside the tax
   year. Missing references or unexpected transaction types are flagged;
   duplicated application IDs fail. Repeated payment/charge pairs with distinct
   IDs remain separate. Neither `DISTINCT` nor grouping hides reapplications.
   The review calculation validates cancelling reverse-direction `Y` pairs,
   separates charge credits/payment reversals, and reconciles every stored
   transaction balance before counting retained P-to-C allocations. Unsupported
   flows/flags withhold amounts. The refund allocation workflow is not reused
   as a Canadian tax rule.
5. Apply the owner's fee policy and reconcile a paid retained USD amount before applying
   the exchange rate. An account balance of zero does not prove every charge
   was paid by eligible funding.

Every student extract has `COUNT(*) OVER ()` and tax-year/account controls so a
truncated result or mismatched scope is rejected. Empty extracts still require
their expected column metadata. These checks do not establish warehouse
freshness or a single database snapshot across the sequential queries.

## Eligibility and exchange policy

`config/institutions/mines/tl11a_detail_codes.json` records the report owner's
October 5, 2026 direction: **exclude FEIT and CFEE only; retain all other charge
codes**, including FEAS and HLTH. The `*` rule is the default for charge codes;
an explicit code rule takes precedence. The `eligible` label records inclusion
under that operational policy, not an independent CRA eligibility ruling.
Missing or unknown Banner charge/payment types still require review. Custom
rule files without `*` retain the previous unknown-code review behavior.

Payments, including scholarships, stay separate from charge eligibility. Do not
subtract scholarship income from tuition as a blanket rule. Refunds, reversals,
restrictions and actual payment applications must be reconciled before
certification.

CRA allows annual-average conversion for fees paid throughout the calendar
year. This workflow retrieves the Bank of Canada's **published annual average**
series `FXAUSDCAD` in **CAD per 1 USD**, rather than calculating its own daily
average. Retain the USD amount, multiply by the rate, and round the final CAD
amount to cents. Missing, unpublished or unreachable rates stay unavailable;
there is no daily, current-year or other-year fallback. The requested tax year's
rate is recorded for review; payments in another year require review of the
appropriate payment-year conversion before use.

Sources (verified October 6, 2026):

- [CRA instructions for educational institutions outside Canada](https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/tax-return/completing-a-tax-return/deductions-credits-expenses/line-32300-your-tuition-education-textbook-amounts/recognized-educational-institutions-outside-canada/info-educational-institutions-outside-canada.html), sections “Reporting period” and “Eligible tuition fee.”
- [Bank of Canada annual average rates](https://www.bankofcanada.ca/rates/exchange/annual-average-exchange-rates/), values stated as foreign currency converted into CAD.
- [Bank of Canada published annual data](https://www.bankofcanada.ca/valet/observations/group/FX_RATES_ANNUAL/json?start_date=2017-01-01), including the `FXAUSDCAD` series.
