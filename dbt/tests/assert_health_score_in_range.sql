-- A health score outside 0..100 means a normalizer broke.
select account_id, as_of_date, health_score
from {{ ref('mart_customer_health_daily') }}
where health_score < 0 or health_score > 100
