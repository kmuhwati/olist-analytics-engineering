-- One row per real customer (customer_unique_id). Olist issues a new customer_id per order.
select
    customer_unique_id,
    min(purchased_at)                      as first_order_at,
    date_trunc('month', min(purchased_at)) as cohort_month,
    count(*)                               as n_orders,
    sum(gmv)                               as lifetime_gmv,
    arg_min(customer_state, purchased_at)  as state,
    arg_min(review_score, purchased_at)    as first_review_score,
    arg_min(is_late, purchased_at)         as first_order_late
from {{ ref('fct_orders') }}
where order_status not in ('canceled', 'unavailable')
group by 1
