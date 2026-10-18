-- Order-level rollup of line items. The "primary" seller and category are the
-- ones carrying the most item value in the order.
with items as (
    select
        i.*,
        p.category,
        p.weight_g,
        p.volume_cm3,
        row_number() over (partition by i.order_id order by i.price desc, i.order_item_id) as value_rank
    from {{ ref('stg_olist__order_items') }} i
    left join {{ ref('stg_olist__products') }} p using (product_id)
)
select
    order_id,
    count(*)                                         as n_items,
    count(distinct seller_id)                        as n_sellers,
    sum(price)                                       as item_value,
    sum(freight_value)                               as freight_value,
    sum(coalesce(weight_g, 0))                       as total_weight_g,
    sum(coalesce(volume_cm3, 0))                     as total_volume_cm3,
    max(case when value_rank = 1 then seller_id end) as primary_seller_id,
    max(case when value_rank = 1 then category end)  as primary_category,
    min(shipping_limit_at)                           as shipping_limit_at
from items
group by 1
