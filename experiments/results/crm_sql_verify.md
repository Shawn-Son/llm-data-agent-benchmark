# crmarenapro q12 SQL verification (offline)

| query | real DuckDB result (agent, avg days) | synthetic execution | intent-card warnings |
|---|---|---|---|
| signed_date_sql | [('005Wt000003NDEBIA4', 304.0)] | accept (all synthetic cases agree) | none |
| created_date_sql | [('005Wt000003NJgAIAW', 49.0)] | reject (1 of 1 synthetic cases disagree) | date field: the question anchors the period on "contract company-signed (closing) date" but the SQL filters on "Opportunity.CreatedDate" |

Expected agent (official ground truth): 005Wt000003NDEBIA4 (the signed-date reading).
