-- GRR is at most 100% by construction and never negative; NRR is never negative.
select period_month, window_type, segment, nrr, grr
from {{ ref('mart_retention_nrr_grr') }}
where grr > 1.0 or grr < 0 or nrr < 0
