-- Exactly one row per account per day.
select account_id, as_of_date, count(*) as n
from {{ ref('mart_customer_health_daily') }}
group by 1, 2
having count(*) > 1
