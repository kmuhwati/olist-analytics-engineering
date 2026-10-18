select
    purchase_month,
    count(*)                                                        as orders,
    count(distinct customer_unique_id)                              as customers,
    sum(gmv)                                                        as gmv,
    avg(gmv)                                                        as avg_order_value,
    avg(case when order_status = 'delivered' then is_late::int end) as late_rate,
    avg(review_score)                                               as avg_review,
    avg(case when customer_order_number > 1 then 1.0 else 0.0 end)  as repeat_order_share
from {{ ref('fct_orders') }}
where order_status not in ('canceled', 'unavailable')
group by 1
order by 1
