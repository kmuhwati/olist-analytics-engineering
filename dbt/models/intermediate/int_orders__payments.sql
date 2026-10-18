select
    order_id,
    sum(payment_value)                   as payment_value,
    max(payment_installments)            as max_installments,
    arg_max(payment_type, payment_value) as main_payment_type,
    count(*)                             as n_payments
from {{ ref('stg_olist__payments') }}
group by 1
