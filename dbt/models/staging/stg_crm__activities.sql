select
    cast(id as varchar)                 as activity_id,
    cast(company_id as varchar)         as account_id,
    cast(contact_id as varchar)         as contact_id,
    lower(cast(activity_type as varchar)) as activity_type,
    lower(cast(direction as varchar))   as direction,
    cast(occurred_at as date)           as occurred_at,
    cast(owner_id as varchar)           as owner_id
from {{ source('raw', 'crm_activities') }}
