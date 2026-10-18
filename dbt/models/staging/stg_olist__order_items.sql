select
    order_id,
    order_item_id,
    product_id,
    seller_id,
    cast(shipping_limit_date as timestamp) as shipping_limit_at,
    cast(price as double)                  as price,
    cast(freight_value as double)          as freight_value
from {{ source('olist', 'olist_order_items_dataset') }}
