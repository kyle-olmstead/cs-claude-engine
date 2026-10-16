select
    cast(id as varchar)                 as contact_id,
    cast(company_id as varchar)         as account_id,
    lower(cast(email as varchar))       as email,
    cast(title as varchar)              as title,
    coalesce(lower(cast(seniority as varchar)), 'unknown') as seniority,
    coalesce(lower(cast(persona as varchar)), 'unknown')   as persona,
    cast(function as varchar)           as function,
    coalesce(cast(is_champion as boolean), false)      as is_champion,
    coalesce(cast(is_exec_sponsor as boolean), false)  as is_exec_sponsor,
    cast(left_company_at as date)       as left_company_at,
    cast(enriched_employer as varchar)  as enriched_employer,
    cast(tenure_months as integer)      as tenure_months
from {{ source('raw', 'crm_contacts') }}
