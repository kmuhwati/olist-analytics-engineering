-- Delivery timing in days. Negative days_late = delivered before the promised date.
select
    order_id,
    date_diff('second', purchased_at, delivered_at) / 86400.0          as days_to_deliver,
    date_diff('second', purchased_at, estimated_delivery_at) / 86400.0 as promised_days,
    date_diff('second', estimated_delivery_at, delivered_at) / 86400.0 as days_late,
    date_diff('second', purchased_at, handed_to_carrier_at) / 86400.0  as days_to_carrier,
    delivered_at > estimated_delivery_at + interval 1 day              as is_late
from {{ ref('stg_olist__orders') }}
where delivered_at is not null
