select
    cast(id as varchar)                 as ticket_id,
    cast(company_id as varchar)         as account_id,
    case lower(cast(priority as varchar))
        when 'urgent' then 'P1' when 'high' then 'P2' when 'normal' then 'P3' when 'low' then 'P4'
        else upper(cast(priority as varchar)) end as priority,
    lower(cast(status as varchar))      as status,
    cast(created_at as timestamp)       as created_at,
    cast(first_response_at as timestamp) as first_response_at,
    cast(resolved_at as timestamp)      as resolved_at,
    cast(csat_score as double)          as csat_score
from {{ source('raw', 'support_tickets') }}
