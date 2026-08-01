SELECT 
coalesce(SUM(
CASE WHEN (STRPOS('bill',lower({{p_DateColumnType}})) > 0) THEN
(case when ({{p_RunDate}}::date - bill_date::date)>=0 and ({{p_RunDate}}::date - bill_date::date)<=30 then balance end)
WHEN (STRPOS('due',lower({{p_DateColumnType}})) > 0) THEN
(case when ({{p_RunDate}}::date - due_date::date)>=0 and ({{p_RunDate}}::date - due_date::date)<=30 then balance end)
WHEN (STRPOS('effective',lower({{p_DateColumnType}})) > 0) THEN
(case when ({{p_RunDate}}::date - effective_date::date)>=0 and ({{p_RunDate}}::date - effective_date::date)<=30 then balance end)
 END), 0)  as "0 To 30 Days"
 FROM "odsmgr"."receivable_account_detail"
    LEFT JOIN "odsmgr"."receivable_account"
    ON (("receivable_account_detail"."account_uid" = "receivable_account"."account_uid") AND ("receivable_account_detail"."id"= "receivable_account"."id"))

WHERE (
"receivable_account_detail".balance>0
 [[AND {{p_detailcode}}]]
 [[AND {{p_accountentityind}}]]
 [[AND {{p_academicperiod}}]]
 [[AND {{p_category}}]]
    )