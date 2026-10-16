select
    cast(id as varchar)                 as account_id,
    cast(name as varchar)               as account_name,
    lower(cast(segment as varchar))     as segment,
    cast(owner_id as varchar)           as csm_owner_id,
    cast(industry as varchar)           as industry,
    cast(created_at as date)            as created_at
from {{ source('raw', 'crm_companies') }}
