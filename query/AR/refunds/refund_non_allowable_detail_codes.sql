/* SQL fragment: owner-confirmed TSADETC Non-Allowable Charge = Y snapshot,
   2026-11-14. The flag is not exposed in Insights. Maintain this list from a
   complete filtered Banner export, then regenerate runnable SQL with:
   python -m data_processing.refunds.extract
   These are charge exclusions for Title IV, independent of charge priority.
   See workflows/refunds/README.md for the decision and refresh procedure. */
VALUES
    ('BIKE'),
    ('BLID'),
    ('CFEE'),
    ('COCC'),
    ('COLL'),
    ('HCMC'),
    ('HLCC'),
    ('HLTE'),
    ('LPPF'),
    ('PENL'),
    ('SBAL')
