/* Diagnostic list of TBBACCT rows carrying the RH refund-hold code. */
SELECT * FROM TBBACCT
WHERE tbbacct_deli_code IN ('RH')
LIMIT 20
