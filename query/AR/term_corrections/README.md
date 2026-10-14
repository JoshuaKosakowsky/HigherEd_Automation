# Payments in a term with no charges

`payments_without_charges.sql` is a read-only review list for the first term
correction scenario: a student paid into a term where no charge ever posted.
It does not change Banner or establish the proper destination term.

## Selection and output

Enter the **payment's posted term**, e.g. `202655` to find Summer payments that
may have been intended for Fall `202680`. There is one row per positive payment
transaction with a negative stored balance (available credit), classified as
type `P`, category `CSH` in `TBBDETC`. This reuses the repository's cash category
definition, rather than treating all aid and other type-P credits as cash.
Confirm that Mines' intended payment codes are classified as CSH before use.
Card fees are charges, not payments.

Any type-C transaction in the same student/term excludes the term, even if its
amount is zero or charges were fully reversed. Unmapped or unknown transaction
types also exclude the term because the absence of charges cannot be verified.
Fully applied payments, nonpositive payments/reversals, and noncash credits
are excluded. Student history in `SGBSTDN` is required, but enrollment in the
payment term is not; a first-time Fall student can qualify for a Summer review.
Historical identity and multiple student-history rows do not duplicate payments.

Output includes current CWID/name, posted term, transaction number, detail code,
descriptions, original payment amount, signed stored balance, available credit,
and feed/effective dates. Available Credit is the negated stored payment balance.
It is not a reconstructed allocation, account-wide balance, or approved amount
to transfer. Multiple payments for one student appear separately.

## Publish in Insights

1. Run `validate_term_corrections_schema.sql`; resolve every MISSING field.
2. Paste the report SQL into a native question in the Banner database and name
   it **Payments in a term with no charges**.
3. Configure `payment_term` as a required basic **Text** variable, display name
   **Payment posted term**, entered as six digits. Do not use a Field Filter.
4. Save in the staff AR collection and grant the intended staff view/run access
   using existing Insights permissions. Staff can run/export without editing SQL.
5. Reconcile a known Summer-to-Fall example and negative controls in TSAAREV/
   TGIACCD before operational use. Allow for Insights replication delays.

`Report Row Count` counts the complete SQL population before an API result cap.
For an Insights export, compare this count to the number of exported data rows;
an empty result means no candidates in the selected term.

## App

Administrators select **Connections → Term corrections — Payments in a term
with no charges**, choose TEST or PROD explicitly, enter the payment term, and
save to a new `.xlsx` file. The service rechecks administrator access before
authentication. Both paths use the same SQL and selection rules. The app checks
the reported count, removes the count column from Excel, and refuses to save
an incomplete result; use Insights export if the API caps the selected term.
Existing files are preserved. No new workflow permission grants are needed
because Connections is already an administrator page.

This first check intentionally misses terms that ever had a charge and credits
outside CSH. It does not require later-term charges: early payers may not yet
have been billed. Staff must confirm the intended term, payment availability,
and any restrictions before making a correction through the established process.
