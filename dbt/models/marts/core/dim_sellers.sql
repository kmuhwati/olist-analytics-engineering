select
    s.seller_id,
    s.seller_state,
    s.seller_city,
    min(o.purchased_at) as first_sale_at,
    count(o.order_id)   as orders
from {{ ref('stg_olist__sellers') }} s
left join {{ ref('fct_orders') }} o using (seller_id)
group by all
