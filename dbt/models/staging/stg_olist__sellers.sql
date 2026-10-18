select
    seller_id,
    {{ zip_prefix('seller_zip_code_prefix') }} as seller_zip_prefix,
    seller_city,
    seller_state
from {{ source('olist', 'olist_sellers_dataset') }}
