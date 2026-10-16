select
    cast(company_id as varchar)         as account_id,
    cast(milestone_key as varchar)      as milestone_key,
    cast(reached_at as date)            as reached_at
from {{ source('raw', 'product_value_milestones') }}
