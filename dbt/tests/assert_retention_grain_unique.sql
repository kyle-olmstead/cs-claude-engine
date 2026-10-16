select period_month, window_type, segment, count(*) as n
from {{ ref('mart_retention_nrr_grr') }}
group by 1, 2, 3
having count(*) > 1
