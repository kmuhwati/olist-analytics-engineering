select
    customer_id,
    customer_unique_id,
    {{ zip_prefix('customer_zip_code_prefix') }} as customer_zip_prefix,
    customer_city,
    customer_state
from {{ source('olist', 'olist_customers_dataset') }}
