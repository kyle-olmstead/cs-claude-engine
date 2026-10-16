-- Hard-gate overrides cap the score; a capped account can never exceed its cap.
select account_id, as_of_date, health_score
from {{ ref('mart_customer_health_daily') }}
where (ovr_champion_departed and health_score > 60)
   or (ovr_payment_past_due and health_score > 50)
   or (ovr_open_p1_aged and health_score > 65)
   or (ovr_utilization_under_20 and health_score > 55)
