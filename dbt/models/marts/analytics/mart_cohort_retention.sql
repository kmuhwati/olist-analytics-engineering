-- Share of each monthly cohort that orders again k months after their first order.
with activity as (
    select
        d.customer_unique_id,
        d.cohort_month,
        date_diff('month', d.cohort_month, f.purchase_month) as months_since_first
    from {{ ref('dim_customers') }} d
    join {{ ref('fct_orders') }} f using (customer_unique_id)
    where f.order_status not in ('canceled', 'unavailable')
),
sizes as (
    select cohort_month, count(*) as cohort_size
    from {{ ref('dim_customers') }}
    group by 1
)
select
    a.cohort_month,
    a.months_since_first,
    s.cohort_size,
    count(distinct a.customer_unique_id)                       as active_customers,
    count(distinct a.customer_unique_id) * 1.0 / s.cohort_size as retention
from activity a
join sizes s using (cohort_month)
group by 1, 2, 3
order by 1, 2
