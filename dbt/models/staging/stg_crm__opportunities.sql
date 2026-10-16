select
    cast(id as varchar)                 as opportunity_id,
    cast(company_id as varchar)         as account_id,
    lower(cast(type as varchar))        as type,
    cast(stage as varchar)              as stage,
    cast(amount as double)              as amount,
    cast(created_at as date)            as created_at,
    cast(close_date as date)            as close_date,
    coalesce(cast(is_closed as boolean), false) as is_closed,
    cast(is_won as boolean)             as is_won
from {{ source('raw', 'crm_opportunities') }}
