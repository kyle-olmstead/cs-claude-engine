-- An account with product history but no logins in 30 days is dormant, not unknown: its DAU/MAU
-- is 0 and its days since last login is a number. Leaving them null would drop those inputs from
-- the score and make a dormant account look healthier than one with a little use.
select account_id, as_of_date, mau_30d, dau_mau_30d, days_since_last_login
from {{ ref('mart_customer_health_daily') }}
where usage_observed
  and mau_30d = 0
  and (dau_mau_30d is null or days_since_last_login is null)
