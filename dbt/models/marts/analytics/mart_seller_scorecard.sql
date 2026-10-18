select
    seller_id,
    any_value(seller_state)       as seller_state,
    count(*)                      as orders,
    sum(gmv)                      as gmv,
    avg(is_late::int)             as late_rate,
    avg(days_to_carrier)          as avg_days_to_carrier,
    avg(review_score)             as avg_review,
    avg((review_score <= 2)::int) as bad_review_rate,
    sum(is_late::int)             as late_orders
from {{ ref('fct_orders') }}
where order_status = 'delivered' and delivered_at is not null and seller_id is not null
group by 1
