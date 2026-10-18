-- One row per order: the central fact table for marketplace analytics.
with orders as (select * from {{ ref('stg_olist__orders') }}),
customers as (select * from {{ ref('stg_olist__customers') }}),
sellers as (select * from {{ ref('stg_olist__sellers') }}),
zips as (select * from {{ ref('stg_olist__zip_centroids') }})
select
    o.order_id,
    c.customer_unique_id,
    o.order_status,
    o.purchased_at,
    date_trunc('month', o.purchased_at)                       as purchase_month,
    o.delivered_at,
    o.estimated_delivery_at,
    c.customer_state,
    s.seller_state,
    i.primary_seller_id                                       as seller_id,
    i.primary_category                                        as category,
    i.n_items,
    i.n_sellers,
    i.item_value,
    i.freight_value,
    i.item_value + i.freight_value                            as gmv,
    i.total_weight_g,
    i.total_volume_cm3,
    p.payment_value,
    p.max_installments,
    p.main_payment_type,
    d.days_to_deliver,
    d.promised_days,
    d.days_late,
    d.days_to_carrier,
    d.is_late,
    {{ haversine_km('cz.lat', 'cz.lng', 'sz.lat', 'sz.lng') }} as distance_km,
    c.customer_state = s.seller_state                         as same_state,
    r.review_score,
    r.has_comment                                             as review_has_comment,
    row_number() over (partition by c.customer_unique_id order by o.purchased_at) as customer_order_number
from orders o
join customers c using (customer_id)
left join {{ ref('int_orders__items') }} i using (order_id)
left join {{ ref('int_orders__payments') }} p using (order_id)
left join {{ ref('int_orders__delivery') }} d using (order_id)
left join {{ ref('stg_olist__reviews') }} r using (order_id)
left join sellers s on s.seller_id = i.primary_seller_id
left join zips cz on cz.zip_prefix = c.customer_zip_prefix
left join zips sz on sz.zip_prefix = s.seller_zip_prefix
