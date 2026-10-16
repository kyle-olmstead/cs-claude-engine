-- end_arr_cohort = start + expansion - contraction - churn, to the cent.
select period_month, window_type, segment, start_arr, expansion_arr, contraction_arr, churn_arr, end_arr_cohort
from {{ ref('mart_retention_nrr_grr') }}
where abs((start_arr + expansion_arr - contraction_arr - churn_arr) - end_arr_cohort) > 0.01
