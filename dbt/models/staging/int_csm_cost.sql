select
    cast(owner_id as varchar)           as csm_owner_id,
    cast(month as date)                 as month,
    cast(fully_loaded_cost as double)   as fully_loaded_cost
from {{ source('raw', 'csm_cost') }}
