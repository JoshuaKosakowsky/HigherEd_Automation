# Contact information lookup

`OS_Checks.sql` returns current identity, preferred active university email, and
primary telephone information for people whose qualifying email record changed
within the last six years.

Despite its historical filename, the SQL does **not** query a check, payment,
refund, or outstanding-check population. It should be treated only as a contact
lookup until an authoritative outstanding-check population is joined to it.

## Data model

- `GOREMAL` supplies email type, address, status, preference, and activity date.
- `SPRIDEN` supplies the current CWID and name.
- `SPRTELE` supplies rows marked as the primary telephone.

The filter requires:

- university email type `UNIV`
- preferred indicator `Y`
- active status `A`
- email activity within six years of the current month

## Run order and validation

1. Run `validate_contact_schema.sql` and resolve every `MISSING` result.
2. Confirm that `UNIV`, `A`, and `Y` retain their expected local meanings.
3. Check whether multiple primary telephone rows can exist for one PIDM; if so,
   one person can appear more than once.
4. If this is to become an outstanding-check report, first identify and validate
   the authoritative check population and its PIDM relationship. Do not infer
   outstanding-check status from email activity.
