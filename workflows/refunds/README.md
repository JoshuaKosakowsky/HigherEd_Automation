# Refund review workflow

This read-only workflow moves the expensive allocation work out of Insights.
It does not approve or issue refunds.

For a single Insights execution, `query/AR/refunds/Refunds.sql` also implements
the current allocation rules entirely in SQL. See the
[single-query guide](../../query/AR/refunds/README.md#single-query-alternative-refundssql)
for its execution design and performance limits. The SQL result is one account
report; this Python workflow adds the refund-type workbook tabs.

## What runs where

For the normal manual process, Insights runs two flat queries. One returns
TBRACCD rows with current TBBDETC metadata; the other returns identity, account
controls, ED holds, selected student mailing addresses, and RLRPAPP Parent PLUS authorization. Each response
includes a total-row guard so Python stops if the website download is truncated.
An ED hold counts as active when its end date is December 31, 2099 or later;
this includes the Banner and cashnet far-future dates.

The local Python process then performs:

- payment and charge reversal netting;
- Mines term and Fall-through-Summer fiscal-year mapping;
- separate charge pools for every term and priority, processed oldest term first;
- a settled-history boundary at the latest completed term where the cumulative
  raw account balance and every stored transaction balance in that prefix are
  known to be zero, preventing closed payments and refunds from being reopened
  while retaining unresolved, offsetting restricted credits and charges;
- Title IV classification and separate $200 giving/receiving fiscal-year caps;
- unrestricted cross-term allocation;
- Banner positional priority matching;
- a common artificial `000` matching/ordering band for stored `800` and `000`
  payments, including TPDT/TPPY and COFP;
- exclusion of Non-Allowable Charges from Title IV payment application;
- earliest transaction-number tie breaking;
- FDPL ownership by aid year and PLUS authorization;
- ACH/credit-card delivery routing and review statuses; and
- Excel output grouped into plain worksheets by refund method and review type.

Financial calculations use `Decimal` cents rather than binary floating point.

### Population and refund amounts

The two exports share one candidate definition: target-term activity, a
qualifying HOMP charge, any TPPY history, **or** a negative stored
payment balance in the last two years of terms through the target term. The
lookback starts with the whole term containing `run_date - 2 years` (September
7, 2026 starts at `202480`). It selects accounts, not transactions: selected
accounts retain their full history. There is no five-year history cutoff. A CWID
filter selects that account directly.

An amount owed in Summer and an equal credit in Fall ordinarily produces no
refund proposal. The exception is unused Title IV funding with confirmed
Non-Allowable Charges still owed, as described below. These accounts may have
a negative, zero, or positive full-account balance.

From **0.29.2**, a fully settled account is excluded before allocation when
charges minus payments across its complete history equal zero, all transaction
amounts are present, and **every individual stored transaction balance is present
and zero**. This includes the current term and respects completed manual cash
applications instead of reconstructing an already resolved late-fee refund.
Offsetting balances such as a $40 fee and a -$40 aid balance do not qualify,
even when they occur within the same detail-code group. A real account credit,
missing amount, or missing balance also cannot satisfy the settlement check.

The owner confirmed this settlement rule and that Trans Paid is sparse and not
required evidence of the staff correction. The check uses the resulting balances;
it does not require a Trans Paid value or date and does not validate application
links. Use fresh, complete extracts after corrections have reached Insights.
Existing extraction completeness checks remain in place. For accounts that are
not fully settled, the [priority and recipient rules](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6690742823)
continue to determine the proposed refund and its recipient.

`full_account_balance` remains charges minus payments across all history,
including refunds already posted. Normally `total_refund_amount` is the account's
net credit. If all remaining unpaid charges are explicitly Non-Allowable, add
the lesser of their unpaid amount and the unused Title IV principal. This allows
the agreed federal refund while leaving those charges owed. Reconstructed source
remainders must equal this permitted refund; otherwise ownership and delivery
remain blocked, without arbitrarily trimming a source. Other unpaid charges,
including fiscal-year cap mismatches, do not qualify for this exception.

From **0.29.1**, recalculated priorities determine the refund source for both aid
and cash. A known Banner stored balance does not cap that source's refundable
remainder. A difference adds `STORED_BALANCE_DIFFERS_FROM_RECONSTRUCTED_ALLOCATION`
as an informational note; the difference alone does not block the split, set
Manual Review status, or change the delivery tab. Missing balances retain their
data-quality review, and a missing balance on a selected aid source still blocks
the split. Known-zero stored balances remain necessary to establish a settled
historical prefix; closed history is not reopened by this correction.

This follows the [priority and recipient decision in issue #29](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6690742823)
and the owner's implementation clarification: recalculated priorities determine
the source even when Banner's existing applications leave the credit on a
different payment. The permitted-refund/net-credit reconciliation above, aid-year
PLUS authorization, funding restrictions, holds, and other delivery checks remain.
Unused FDPL authorized `N` goes to **Refund to Parent**, regardless of student ED.
Authorization `Y` uses **Direct Deposit** with active ED, otherwise **Refund by
Check**, subject to the existing address, clearing, and check-minimum rules.

`HIWR` (Health Insurance Waiver/Offset) directly reduces `HLTH` (Health Insurance)
within the same term and charge-priority pool (`879` for both in the supplied
configuration), before aid or cash is allocated. The posted negative HIWR amount
is a charge adjustment. An equal HLTH/HIWR pair leaves zero insurance charges
and consumes no payment; HIWR is not a separate refundable payment source.

Synthetic acceptance examples:

| Account activity | Expected result |
| --- | --- |
| Summer debt $5,000; Fall credit $5,000 | $0 refund; absent from refund tabs. |
| Summer charges $5,000; Fall unrestricted cash $5,500 | $500 refund after cash covers Summer. |
| Summer cash $5,500; Fall charges $5,000 | $500 refund after cash covers Fall. |
| Same-term HLTH $1,000 and HIWR -$1,000 at priority 879; unapplied cash $100 | Insurance nets to $0 before allocation; the $100 cash credit remains available. |
| Summer tuition $1,000 and applied Title IV aid $1,200; Fall tuition $500 and scholarship $600 with $300 unapplied | Earlier aid applies first; $300 of Fall scholarship remains, without reopening Summer aid. |
| Prior-term charges $200; current charges $1,000; current scholarship $500 at 000 followed by PLUS $800 at 800; Banner shows $100 unused on scholarship and $0 on PLUS | Recalculation leaves $100 on PLUS. Authorization N routes $100 to Refund to Parent with or without ED; Y routes it to Direct Deposit with ED, otherwise Refund by Check. Stored-balance difference is informational. |
| Same example with missing, conflicting, or wrong-aid-year PLUS authorization | $100 net credit remains on Manual Reviews with recipient amounts undetermined. |
| Same example with an RH hold | The entire $100 stays on Refund Holds for either authorized recipient. |
| Earlier charges/cash $200 each; current tuition $1,000, LPPF $40 and Title IV $1,040; all individual balances zero after staff applications | Exclude the fully settled account, including current-term activity; no refund row on any tab. Trans Paid is not required. |
| Same example with LPPF balance $40 and aid balance -$40 | Keep the account for allocation: proposed Title IV refund $40 and unpaid LPPF $40, subject to existing delivery/review rules. |
| Same example with a missing transaction balance or amount | Do not treat the account as fully settled; retain existing missing-data checks. |
| Old-FY charges $1,000; newer Title IV payment $1,200, of which the configured cap applies $200 | Net credit $200 goes to manual review with no recipient/delivery; reconstructed unused $1,000 is diagnostic only. |
| Tuition $1,000; LPPF $100 marked Non-Allowable; Pell $1,200 with $200 unapplied | Refund $200; $100 remains owed; new column identifies the balance. |
| Same example with LPPF $200 or $300 | Refund $200 even though the starting account balance is zero or positive; $200 or $300 remains owed. |
| Tuition $1,000; Non-Allowable fee $100; Pell $1,200 followed by cash $100 | Cash pays the fee; Pell refund $200; new column says No. |

### Priorities, delivery, and review

Priorities without a zero, such as `899` and `869`, match only that exact charge
priority. Existing zero wildcard rules and Title IV fiscal-year limits also
apply across terms. Payments use oldest term first, then descending priority
and earliest transaction number within that term. A later scholarship's higher
priority cannot put it ahead of earlier-term aid. ACH and cards have no special
last-payment band. Stored `800` and `000` use the same artificial `000` for both
matching and order, below other nonzero priorities. TPDT/TPPY and COFP have no
special bands; all compete by transaction number within their payment term.
Original priorities, payment identity, and PLUS ownership remain available to
the calculation. This does not edit Banner's detail-code configuration.

### Title IV refunds that leave charges owed (0.28.0)

The [allocation decision in issue #29](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6690742823)
defines the common priority. In the implementation follow-up, the owner confirmed
removing the sponsor/COF exceptions, keeping oldest-term-first order, and the
$200 Pell refund/$100 LPPF balance example above. The related
[Title IV flag question](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6870164720)
tracks the charge-eligibility context; these confirmations are not live validation.

`TBBDETC_TIV_IND = Y` identifies Title IV payments. A charge marked Non-Allowable
cannot consume those payments, even under the common `000` wildcard. Other
eligible funding can pay it. The funding flag controls this exclusion, not the
payment's original priority: Title IV at `000` is still restricted; non-Title-IV
at `800` can pay these charges under the common wildcard. Charges pool only
within the same term, priority, and Non-Allowable flag. Missing/invalid extracted
flags block recipient splits. Stored aid-balance safeguards still apply.

#### Maintained Non-Allowable list (0.28.1)

PROD Insights exposes neither `TBBDETC_NON_ALLOW_CHG_IND` nor the spelling shown
by Banner's UI item, `TBBDECT_NON_ALLOW_CHG_IND`. Referencing the first field in
0.28.0 caused the refund extraction to fail with HTTP 400. On 2026-11-14, the owner
provided a complete TSADETC export filtered to Non-Allowable Charge `Y` and
explicitly authorized using those 11 codes as the current standing list in the
implementation discussion. This replaces the unavailable source field; it does
not change the funding restriction agreed in issue #29.

The authoritative list is
[`refund_non_allowable_detail_codes.sql`](../../query/AR/refunds/refund_non_allowable_detail_codes.sql):
BIKE, BLID, CFEE, COCC, COLL, HCMC, HLCC, HLTE, LPPF, PENL, SBAL.
BIKE is priority `889`; HCMC and HLCC are `799`; the remaining eight are `789`
or below. The list applies regardless of a code's priority. All listed detail
codes produce `non_allowable_charge_ind = Y`; other codes with existing Banner
detail metadata produce `N`. Missing detail metadata stays unknown. This is a
maintained snapshot, not a live read of Banner's checkbox, and `INST_CHG_IND`
is not used as a substitute.

When Banner's Non-Allowable configuration changes, obtain the complete filtered
export again, update the list and its snapshot date, and run from the repository
root:

```powershell
python -m data_processing.refunds.extract
```

This regenerates both manual extracts and the marked policy block in the
standalone `Refunds.sql`. API extracts use the same source file directly.
Regenerate both manual downloads or start a fresh API extraction after a list
change. Cache format 7 includes the policy fingerprint, so resume/offline mode
rejects caches made with a different list. This list does not automatically
pick up new flags set in Banner.

Additional synthetic acceptance cases: tuition $1,000, one $100 charge using
BIKE, HCMC or LPPF, and Title IV $1,200 with $200 unapplied yield refund $200 and $100 still owed,
whether the Title IV payment priority is `800` or `000`. The same account with
non-Title-IV funds at either priority can pay the fee, leaving refund $100 and
no unpaid fee. An unlisted allowable charge at `789` can be paid by Title IV.

Every workbook tab includes **Title IV Refund Leaves Balance Due**, immediately
after **Total_Owed_to_Student**. From **0.28.3**, it contains only `Yes` or `No`:
`Yes` means a calculated Title IV refund would leave non-allowable charges owed;
all other cases, including an unresolved recipient split, display `No`. A `No`
does not clear a review requirement: unresolved cases retain their existing
`review_status`, `refund_split_status`, and `review_reasons`. The flag describes
the account-level proposal, including when portions appear on separate tabs.
Holds and sponsor/parent review routing still apply. The column supports staff
follow-up; it neither confirms issuance nor sends email.

This implements the explicit Non-Allowable exclusion only. Institutional-charge
authorization (`TBBDETC_INST_CHG_IND` and the student's authorization records)
is not inferred; its extraction and rules remain a separate unresolved scope.
Before operational use, compare representative Banner accounts with fresh
extracts, including the `889` BIKE exception and unrestricted payments.

### Previously issued refunds and voids (0.29.3)

After ordinary charges are allocated oldest-term first, posted `ARFD`/`RFND`
student refunds are deducted once from the remaining payment sources. This
reconciliation bypasses priority matching because the money has already been
issued. Same-code reversals are netted first. `RFDP` remains an ordinary charge.

The owner requested the 2026-11-17 correction after later charges displaced the
funding of settled refunds in diagnostic extracts. This retains the
[priority/recipient decision](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6690742823)
and addresses the observed check/void/ACH-reissue case from the
[void-handling topic](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/33).
The broader void cases in that issue are not all resolved by this correction.

A refund may reconcile against current source remainders, including later
payments, only when its stored balance is known zero and either:

- Complete amounts show sufficient account credit immediately before it was
  posted, ordered by transaction number; or
- It belongs to a transaction prefix with zero cumulative charges-minus-payments,
  all amounts present, and every individual stored balance known zero.

The second condition recognizes a refund that was subsequently settled. Neither
an aggregate zero with offsetting balances nor a missing balance proves this.
This evidence does **not** remove additional history from allocation or change
charge priorities, Title IV eligibility or fiscal-year caps. Unproved refunds
retain the earlier-payment restriction. Any residual/source mismatch still
blocks recipient assignment; the existing matched-amount review note remains.

`RFDV` is excluded from ordinary charge pools. A negative void cancels only a
unique earlier `ARFD`/`RFND` with the same term and exact surviving amount, with
both stored balances known zero. The match must be unique in both directions.
A possible equal-amount parent refund or another matching student refund with an
unknown/unsettled balance prevents automatic pairing. A later reissue remains a
separate issued refund. Partial, unmatched, ambiguous,
duplicate, positive, cross-term, parent, or unsettled voids block the split with
`REFUND_VOID_REQUIRES_REVIEW`; no original-refund link is inferred.

Synthetic acceptance examples (all balances known zero unless specified):

| Transactions in posting order | Expected result |
| --- | --- |
| Tuition $1,000; payment $2,000; issued refund $1,000; new grant $500 with -$200 stored balance; later charge $300 | Student credit $200 from the new grant; the prior refund is deducted once. |
| Same history, but the issued refund balance is missing or $1,000 | Recipient amounts remain undetermined; later payment does not bypass the unresolved refund. |
| Refund $100; payment $100, both settled; new grant $50 with -$20 balance; charge $30 | Completed transaction prefix proves settlement; student credit $20. Offsetting/unknown prefix balances do not qualify. |
| Tuition $100; scholarship $2,100; RFND $2,000; RFDV -$2,000; ARFD $2,000; new grant $200 with -$200 balance | Cancel the unique check/void pair, count the ACH reissue once, and propose $200. |
| Same check with an RFDV of only -$1,000, or two possible matching refunds | Manual Reviews; no guessed cancellation. |
| New credit depends on a payment assigned to a term after the target term | Manual Reviews with future-term activity excluded, regardless of its effective date. |

Parent PLUS authorization, RH/third-party/housing controls, missing-data checks,
net-credit and Title IV exceptions, clearing reserves, check minimums, addresses,
and original-method delivery rules remain in force. Active ED selects DD only
for an otherwise determined student portion.

Only each unused ACH/card source remainder routes to Transact. Remaining aid,
scholarship, and PLUS funds authorized for the student use the student's normal
`ARFD (System)` or `RFND (CHECK)` route; PLUS authorized for the parent uses
`RFDP`. `CRAM`, `CRDS`, `CRMC`, and `CRVC` display their own code plus `(Transact)`
with no clearing wait. ACHK uses its effective date: available on day 16
(August 1 becomes August 17), through day 180. Older funds show
`AFRD (Transact) - May Be Too Old`. Reversals are netted before identifying
surviving sources. From 0.28.4, both CHCK and ACHK use the payment reserve below,
including payments already applied to charges. Available original-method
portions retain their delivery order and are capped at available student funds;
remaining ordinary student funds use ED or check. Holds continue to override
every delivery route.

### Payment clearing reserves (0.28.4)

Each surviving positive CHCK/ACHK payment clears on **Effective Date +16
calendar days**: it remains reserved before that date and is eligible on that
date. Its remaining
principal after reversals is reserved even if applied to charges or in settled
history. Reversals use the existing term/aid-year/detail-code grouping and reduce
the newest positive payment first. Fully reversed payments create no reserve.
Each uncleared payment also requests a temporary **$35 insurance reserve**.
Reserve amounts are recomputed on every run; payments release independently as
they clear. Withholding does not add a charge or change refund ownership.

Calculate the normal student/parent refund split first, retaining existing
reconciliation and Title IV checks. Then:

1. Reserve up to $35 per uncleared payment from the student's refundable amount.
   Limit insurance to available student funds; none spills into a parent refund.
2. Reserve the uncleared payment principal from the remaining student funds first,
   then from parent funds, capped at their refundable amounts.
3. Route available portions normally, with reserved portions on **Payment
   Clearing**. No dollar appears in both payable and reserved portions.

`student_refund_amount`, `parent_refund_amount`, and `total_refund_amount` retain
the gross amounts owed. New available/reserved columns explain when those
amounts can be issued. `clearing_payment_amount` is the full uncleared principal;
it can exceed the amount actually reserved when credit is smaller.
`clearing_insurance_amount` is the insurance actually reserved from student funds.
Next/Final Clearing Date show the earliest/latest known eligibility dates;
rerun on the next date to recompute availability. Missing or future Effective
Dates block the recipient split and require manual review, including for applied
payments. A valid split with reserved amounts has `WAIT_PAYMENT_CLEARING` status.
RH and other account-level review routing retain precedence and keep the gross
account together with its reserve context.

The reserve and check minimum originate in [issue #31](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/31).
During implementation on 2026-11-15, the owner retained **Effective Date** in
place of the issue comment's earlier Feed Date wording, confirmed remaining
principal after partial reversal, and specified student-first principal with
student-only insurance. These are the implemented decisions.

Synthetic acceptance cases, before the payment clears:

| Student owed | Parent owed | Uncleared payments | Student available | Parent available | Total reserved |
| ---: | ---: | --- | ---: | ---: | ---: |
| $2,035 | $0 | One $1,000 payment applied to $1,000 tuition | $1,000 | $0 | $1,035 |
| $2,035 | $0 | One $1,000 payment less a $400 reversal | $1,400 | $0 | $635 |
| $2,035 | $0 | Two separate $500 payments | $965 | $0 | $1,070 |
| $100 | $2,000 | One $1,000 payment | $0 | $1,065 | $1,035 |
| $10 | $2,000 | One $1,000 payment | $0 | $1,000 | $1,010 |
| $0 | $2,000 | One $1,000 payment | $0 | $1,000 | $1,000 |
| $20 | $0 | One $1,000 payment | $0 | $0 | $20 |

For the first example, day 16 releases all $2,035 if nothing has been issued.
If the permitted $1,000 was already issued and posted, only $1,035 remains for
release. Two $500 payments dated four days apart release independently: after
the first clears, the remaining reserve is $535, then zero after the second.

- Surviving target-term refund sources `C529` or `Z0LE` add `Possible Third Party
  refund`. A surviving TPPY payment adds the same review when it is in the target
  term or effective 0–32 days ago in any term. TPPY still qualifies after it has
  been applied to charges. Independently, **any TPPY activity in a term with a
  net credit requires review, even if fully reversed**, regardless of transaction
  age or selected target term. Unknown financial data in a TPPY term also requires
  review. The matched code remains visible in `third_party_match_source`, and automatic delivery is
  suppressed with `THIRD_PARTY_REVIEW`. Existing third-party account flags remain
  effective.
- A surviving positive HOMP charge in the target term, or effective 0–32 days
  ago in any term, adds `Mines Park Charge - Review`. This includes paid charges
  in settled history, but excludes fully reversed charges. Refund amounts and
  delivery remain visible for staff review.

These implement the institution's supplied allocation policies; the workbook
remains a review proposal, not approval to disburse funds.

### Third-party review details (0.27.0)

The confirmed review rule and requested context are tracked in
[issue #29, sponsor review comment](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/29#issuecomment-6691269422).
This extends review routing; it does not change payment allocation or authorize
returning sponsor funds to the student.

Only **Third Party Reviews** adds these columns:

| Header | Meaning |
| --- | --- |
| Sponsor(s) | Sponsor name from current SPRIDEN identity |
| Sponsor ID(s) | Sponsor ID from current SPRIDEN identity |
| Contract Number(s) | TBBCSTU contract number, retained as text |
| Current Term | Calendar-derived term using the run date and existing Mines term boundaries |
| TPPY Current Term Total | Signed TBRACCD amounts for TPPY in that current term, including reversals |
| Z0LE Current Term Total | Signed TBRACCD amounts for Z0LE in that current term, including reversals |
| Z0LE Activity_Last 7 Days | Yes for any Z0LE activity whose Feed Date is today or one of the preceding six calendar days; otherwise No |

Totals are transaction totals, not remaining unapplied balances. The seven-day
flag checks all extracted terms and includes reversal activity; it does not use
Effective Date or Activity Date. Missing amounts leave the affected total blank
and retain existing data-quality review reasons.

Sponsor attachments cover the calendar-derived current term and terms with
TPPY, Z0LE, or C529 activity. Lists are aligned by sponsor ID, sponsor PIDM and
contract number; a sponsor repeats when it has multiple contracts. Duplicate
attachments are removed before aggregation and PLUS authorization joins, without
multiplying transactions. Missing sponsor identity is labeled unavailable;
missing attachments remain blank. Attachment deletion/authorization flags are
not inferred as ownership decisions: this is context for manual review.

Synthetic acceptance cases:

- TPPY +100 and -100, plus a separate 50 payment in the same term: review the
  50 account credit even though TPPY nets to zero, including historical terms.
- Fully reversed TPPY in a zero-balance old term, with credit only in another
  term: the new same-term rule does not trigger; existing review rules still apply.
- Current-term TPPY +100/-20 and Z0LE +50/-10: show 80 and 40, regardless of
  an overridden target term. Duplicate PLUS rows do not change either total.
- Z0LE Feed Date six days before the run: Yes; seven days before or tomorrow: No.
- RH plus a third-party review condition: the entire refund remains on Refund
  Holds, preserving the third-party reason. Third Party Reviews stays empty.

**Refresh both manual downloads or start a new API extraction after upgrading.**
Old downloads lacking Feed Date, sponsor columns, or the Non-Allowable Charge
flag or student-address fields are rejected with a request to rerun the current
export SQL. Caches now use format version 8 and include both policy fingerprints;
older formats cannot resume. Run `validate_refund_schema.sql` to confirm SPRADDR, TBBCSTU fields and
TBRACCD_FEED_DATE in the actual Insights schema, then compare representative
sponsors/contracts against TSACONT before operational use. Candidate selection
now includes historical TPPY accounts; production-size extraction timing needs
local verification.

The standalone `Refunds.sql` retains its existing output columns and shares the
new TPPY review condition. The sponsor-detail columns are produced by the Python
workflow from the flat extracts, not by that standalone allocation report.

### Student check address review (0.28.5)

[Issue #36's decision comment](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/36#issuecomment-6898592530)
defines the student address priorities and flags. In the implementation discussion
on 2026-11-15, the owner confirmed nation code `US`, a dedicated **Check Address
Review** tab, and domestic fallback for the 50 states, DC, territories and military
postal states. Parent-address validation remains pending; this patch covers
student checks only. Existing Parent PLUS authorization and recipient amounts
remain unchanged. Student addresses are never substituted for parent addresses.

The shared `query/AR/refunds/refund_student_addresses.sql` selects from
`saturn.spraddr` for both extracts and the standalone report:

1. Consider PR → TX → MA → PA → BI. Skip absent/entirely blank records, inactive
   status `I`, future start dates and expired end dates. Start/end dates are
   inclusive of the refund run date; NULL bounds are open-ended.
2. Within each type, use the highest `SPRADDR_SEQNO` as the newest added record.
   Choose that record before classifying its country. An older domestic record
   of the same type cannot override a newer foreign record. All displayed address
   fields come from one selected record.
3. Nation `US` qualifies as domestic. A nonblank different nation does not,
   even when State says CO or another domestic code. With blank nation, accept
   the 50 state abbreviations, DC, AS/GU/MP/PR/VI, and AA/AE/AP. Other or blank
   state codes are unknown for this purpose. Whitespace/case are normalized.
4. Select the first domestic address in priority order. A PR selection has no
   flag; any later type, including when PR is missing, gives **UPDATE WORKDAY**.
   If no domestic address exists, show **Withhold check refund** and retain the
   highest-priority current foreign/unknown address for staff context, or blank
   fields when none exists. This check classifies geography; it does not validate
   street deliverability or confirm Workday has the same address.

The workbook adds **Student Address Type**, **Student Address Line 1/2/3**,
**Student Address City/State/ZIP/Nation**, and **Student Check Address Flag**.
The flag is populated only when an available student check portion exists;
both flag values use red text. These are student/account context columns on
every sheet, not parent mailing instructions. ZIP values retain leading zeros.

Flagged check portions go to **Check Address Review**, pending the Workday
update/verification or resolution of the missing domestic address. Eligible
ACH/card, direct deposit and parent portions keep their existing routes; no
refund amount is forfeited or reassigned. Clearing reserves remain on Payment
Clearing. A flagged check below $25 also goes to Check Address Review, with the
minimum warning retained; correcting its address does not waive the minimum.
RH and existing whole-account ownership/manual reviews keep their precedence.
`STUDENT_CHECK_ADDRESS_REVIEW` appears in review reasons, with status
`WAIT_CHECK_ADDRESS` unless an existing hold/manual review or clearing reserve
takes precedence. SQL supplies the same fields/flags; Excel routing and red
formatting are applied by the workbook exporter.

| Synthetic input | Expected result |
| --- | --- |
| PR nation US | PR address; normal student check route |
| PR Germany; PA blank nation / CO | PA address; UPDATE WORKDAY; Check Address Review |
| Older PR US; newer PR Germany; TX US | TX selected; UPDATE WORKDAY |
| PR absent; MA US | MA selected; UPDATE WORKDAY |
| Blank nation with DC, PR, or AE state | Domestic fallback |
| Foreign nation with CO state; no other domestic address | Withhold check refund |
| No address, or blank nation/state | Withhold check refund |
| $100 ACH + $100 flagged student check + $75 parent | $100 ACH tab, $100 Check Address Review, $75 Refund to Parent |
| $10 flagged student check | Check Address Review; also retain below-$25 warning |
| RH plus an address flag | Entire refund stays on Refund Holds |

Refresh both manual downloads or start a fresh API extraction. Run the updated
`validate_refund_schema.sql` in the target Insights environment and resolve
missing SPRADDR fields before the first full run. Synthetic tests do not verify
the live replica or Workday import. Updating Workday remains a staff action.

### Workbook tabs

The workbook has these tabs, including headers when a category is empty:

- **ACH or CC Refunds** (light yellow tab): available ACH and credit-card portions.
- **Refund by Check** (light green tab): student `RFND (CHECK)` portions meeting
  the minimum and without an address-review flag.
- **Check Refund < 25:** student check portions below $25.00; do not issue a
  check for these amounts. From 0.28.4 the minimum applies to each student check
  portion after splitting by delivery method. Exactly $25.00 stays on Refund
  by Check. Eligible ACH/card and direct-deposit portions retain their normal
  tabs even when the same account has a check portion below the minimum.
- **Check Address Review:** flagged student check portions, with red
  **UPDATE WORKDAY** or **Withhold check refund** in Student Check Address Flag.
  Below-$25 portions also retain their minimum warning here.
- **Refund to Parent** (light orange tab): parent `RFDP` portions.
- **Direct Deposit** (light blue tab): student `ARFD (Direct Deposit)` portions.
- **Third Party Reviews:** the entire account refund pending ownership review.
- **Refund Holds:** the entire account refund when RH is present, including any
  student and parent portions. No portion remains on a delivery or other review
  tab while the hold is active.
- **Payment Clearing:** student/parent portions reserved for uncleared CHCK/ACHK
  payments and student-only insurance. Do not issue these reserved amounts.
  Available portions can appear on their normal method tabs at the same time.
- **ACH Clearing:** retained for the earlier per-source ACH wait format; new
  calculated CHCK/ACHK reserves appear on Payment Clearing.
- **ACH Reviews:** ACH portions over 180 days old or requiring effective-date review.
- **Mines Park Reviews:** the entire account refund pending housing review.
- **Manual Reviews:** undetermined splits, unrecognized delivery methods, or
  delivery components that do not reconcile to recipient amounts.

RH takes precedence over every delivery and review tab. Without RH, third-party
review takes precedence over Mines Park review. All applicable reasons remain
visible so staff can address them after a hold is removed. Other existing review
statuses and reasons stay on the applicable method tabs: a tab assignment is
**not approval to issue a refund**.

The $25 minimum does not apply to Parent PLUS refunds payable to the parent;
those remain on Refund to Parent. Existing RH, ownership and manual-review
routing take precedence over the small-check tab. The owner confirmed the
minimum and parent exception in [issue #31](https://github.com/JoshuaKosakowsky/HigherEd_Automation/issues/31#issuecomment-6690980646),
then confirmed in the implementation discussion on 2026-11-15 that mixed
refunds are separated by delivery portion. Synthetic examples: $24.99 by check
is held on Check Refund < 25, $25.00 by check remains on Refund by Check, and
$100 by ACH plus $10 by student check plus $5 to a parent appears as $100 on
ACH or CC Refunds, $10 on Check Refund < 25, and $5 on Refund to Parent.
Python and standalone SQL also flag `STUDENT_CHECK_REFUND_BELOW_25` in review
reasons. `WAIT_CHECK_MINIMUM` is the status unless a hold, manual review,
clearing reserve or address review takes precedence; other available delivery portions retain
their routes.

Mixed refunds can appear on multiple tabs, but each account appears at most
once per tab. **Detail_Code_Delivery** identifies that tab's method(s), and
**Detail_Code_Refund_Amt** contains only that portion. Sum this portion across
tabs; account-level totals repeat as context. **Detail_Code_Note** explains
account review placement. Retained report columns keep their values and relative
order after these three fields, which follow the student's name.

All tabs use the following displayed-header mapping and retain the student/parent
context fields listed below. Other retained columns keep their original order
and names.

| Original field | Displayed header |
| --- | --- |
| `cwid` | `CWID` |
| `last_name` | `Last_Name` |
| `first_name` | `First_Name` |
| `tab_delivery` | `Detail_Code_Delivery` |
| `tab_refund_amount` | `Detail_Code_Refund_Amt` |
| `tab_review_note` | `Detail_Code_Note` |
| `full_account_balance` | `Current_Total_Balance` |
| `total_refund_amount` | `Total_Owed_to_Student` |
| `student_refund_available_amount` | `Student Available Now` |
| `parent_refund_available_amount` | `Parent Available Now` |
| `student_clearing_reserve_amount` | `Student Clearing Reserve` |
| `parent_clearing_reserve_amount` | `Parent Clearing Reserve` |
| `clearing_payment_amount` | `Uncleared Payment Principal` |
| `clearing_insurance_amount` | `Student Insurance Reserve` |
| `clearing_payment_count` | `Uncleared Payment Count` |
| `clearing_next_eligible_date` | `Next Clearing Date` |
| `clearing_final_eligible_date` | `Final Clearing Date` |
| `student_address_type` | `Student Address Type` |
| `student_address_line1` / `line2` / `line3` | `Student Address Line 1` / `2` / `3` |
| `student_address_city` | `Student Address City` |
| `student_address_state` | `Student Address State` |
| `student_address_zip` | `Student Address ZIP` |
| `student_address_nation` | `Student Address Nation` |
| `student_check_address_flag` | `Student Check Address Flag` |
| `proposed_student_delivery` | `Proposed_DetailCode&Amt` |
| `raw_delinquency_code` | `Active RH` |
| `active_ed_ind` | `Active ED` |
| `ed_activity_date` | `ED Start` |
| `plus_to_student_status` | `PPL to Student` |

Every tab omits `original_payment_row_count`, `deceased_ind`, `deceased_date`,
`confidential_ind`, `ambiguous_source_pool_count`, `last_ar_activity_date`, and
`account_control_activity_date`. These omitted fields remain available internally.
Every tab includes `student_refund_amount`, `proposed_parent_delivery`,
`parent_refund_amount`, `plus_to_student_status` (displayed as **PPL to Student**),
`refund_hold_ind`, and `fdpl_aidy_code` as account context. These fields repeat
when an account appears on multiple tabs; they are not the tab's refund portion.
On **Refund to Parent**, **Detail_Code_Refund_Amt** is the available parent
portion; `parent_refund_amount` includes any amount still reserved for clearing.
Sum **Detail_Code_Refund_Amt** when combining portions across tabs;
**Total_Owed_to_Student** remains the account-level total.

Both **Detail_Code_Delivery** and **Proposed_DetailCode&Amt** display the system
route as `ARFD (Direct Deposit)`, including mixed-method values. The underlying
detail code remains ARFD; the internal allocation report uses `ARFD (System)`.
The renamed columns retain their existing values: **Active RH** is the raw
delinquency code, **Active ED** is the ED indicator, and **ED Start** is the
existing ED hold activity timestamp.

The sheets use ordinary cells with formatted headers, currency/date formats,
frozen headers, and regular column filters. They contain no Excel Table objects.
This presentation change does not alter allocation, ownership, or SQL scope.

## Run

Complete the repository's normal `setup.ps1` process. In the Insights website:

1. Run `query/AR/refunds/refund_transactions_manual.sql` and download the full
   result as XLSX or CSV.
2. Run `query/AR/refunds/refund_context_manual.sql` with the same settings and
   download the full result.
3. Rename and place them under `data/refunds/input` as
   `refund_transactions.xlsx` and `refund_context.xlsx`.

Then run from the repository root:

```powershell
.\launcher\run_refunds.ps1 `
    -TargetTerm 202680 `
    -TransactionsFile ".\data\refunds\input\refund_transactions.xlsx" `
    -ContextFile ".\data\refunds\input\refund_context.xlsx"
```

The output workbook is written under `data/refunds` by default. CSV and Excel
files are excluded by `.gitignore`; never commit or move these student-account
extracts into the repository as another file type.

The files may remain in Downloads instead. Pass their complete paths to
`-TransactionsFile` and `-ContextFile`; Python does not require a particular
folder. The recommended input folder simply makes the two files easy to identify
and is already protected by `.gitignore`.

Administrators may run this same manual-download pipeline from **Refund Review**
in the Mines Bursar Automation desktop app. The GUI accepts a path, Browse
selection, or file drop for each download and refuses to overwrite an existing
review workbook. The analyst and cashier views are not assigned this workflow.

For a single-account validation, set the same `cwid_filter` inside both manual
SQL files before running them. Leave `cwid_filter` NULL for the population.
Do not save or commit a populated CWID in either SQL file.

The API/batched mode remains available when the existing Insights API connection
has been configured. It does not require manual downloads:

```powershell
.\launcher\run_refunds.ps1 -TargetTerm 202680
```

The GUI also supports **Cancel run**, or cancelling and closing from the window
close button. Its shared progress display shows extraction batches and partitions,
transaction normalization, completed account calculations, worksheet creation,
formatting, saving, and publication. Percentages describe the current stage;
unknown totals use an activity bar. Elapsed time remains visible throughout.
Cancellation waits for an in-flight request to return or time out,
checks between account calculations and workbook stages, and discards staged
output before publication. A successfully published workbook remains available
if cancellation is requested after the publication step. Other workflows retain
their existing close restrictions. Query and processing timings appear in the
GUI log and launcher progress output.

## Recover from failures

Recovery applies to API/batched mode. From **0.28.2**, the extractor retries a
read-only partition query after connection errors, timeouts, or HTTP
429/502/503/504 responses: at most three attempts, with 2- and 5-second waits.
Cancellation interrupts the wait; authentication/permission errors, invalid
SQL (including HTTP 400), and invalid results are not retried. Completeness
checks still apply to every successful response.

In the GUI, failed or cancelled SQL runs retain complete batches in the operating
system's local user cache under `HigherEdAutomation/refunds`. Rerun the same term
on the same day to resume automatically after reconnecting. Reuse requires the
same authenticated Insights user, connection/database, application version, and
SQL fingerprint, plus the existing manifest checks. The failed top-level batch
starts again; partial children are not saved. The log identifies the cache
directory. Delete it while no run is active to force a fresh extraction, for
example when source records have changed. Resuming uses the original completed
batches and is not a fresh snapshot of those accounts. Successful runs remove
their cache; the next run for that user/database removes earlier dated caches.
An interprocess lock prevents concurrent use of the same user's connection cache.
Versions through 0.28.1 used a temporary directory in the GUI, so this change
cannot restore batches already deleted by a failed older run.

For the PowerShell launcher, use the same term and batch count with `-Resume`:

```powershell
.\launcher\run_refunds.ps1 -TargetTerm 202680 -BatchCount 20 -Resume
```

The API extractor automatically subdivides truncated transaction and context
batches by disjoint PIDM ranges. If a single account's transaction history is
still too large, it subdivides by transaction number. This handles Insights'
response row limit without changing the initial `-BatchCount` or account scope.
PIDM bounds apply inside candidate selection, before full-account balance
aggregation and history joins. Transaction-number bounds apply to the final
transaction extract, so they never alter full-account eligibility. Smaller
queries therefore avoid rebuilding the entire original batch on every retry.
Every part passes the row-count guard, and recombined totals must match the
parent batch before the completed batch is cached. Each filtered query retains
its own row-count guard. Progress is printed by the
launcher and written to the GUI log without account identifiers. Subdivision
is bounded; an indivisible result or a population change that breaks count
reconciliation stops extraction
with a descriptive error rather than accepting incomplete data.

Only complete top-level batches are cached; a failed subdivided batch is
retried in full when resuming. Existing compatible complete caches remain valid.
If a query repeatedly times out, increase `-BatchCount` and start a fresh extraction
without `-Resume`. Changing the batch count changes every PIDM partition, so
old batches cannot safely be mixed with the new run. Manual file downloads
still require complete exports; they cannot be automatically subdivided.

To recalculate an already complete extraction without Insights, use `-Offline`
with the same term, batch count, extract directory, optional CWID, and run date
used for the original extraction. When resuming or recalculating on a later
date, set `-RunDate YYYY-MM-DD` to the original date. The cache manifest also
records the extraction policy version; caches from before this population
change must be extracted again.

Re-download **both** manual exports after an extraction population update.
Older downloads may omit newly eligible accounts. Use identical SQL settings
and pass the matching `-TargetTerm` and `-RunDate` to Python.

The later workbook-tab-only change does not require new SQL downloads; existing
compatible extracts can be recalculated to produce the new layout.

Version 0.28.0 requires the new `non_allowable_charge_ind` transaction column.
Older downloads are rejected with a refresh instruction. Use the updated SQL
for both paired downloads before recalculating. Version 0.28.1 derives this
column from the maintained Non-Allowable list; refresh both downloads after
upgrading or changing that list.

## Validation expectation

Run a known account first by setting `cwid_filter` in both manual SQL files (or
use `-Cwid` in API mode). Compare the workbook to the account activity and the
expected Banner/staff result before running the population. Treat every status
other than `READY_FOR_STAFF_REVIEW` as requiring the listed review or wait
action.
