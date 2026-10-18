select
    case
        when days_late <= -10 then '1. 10+ days early'
        when days_late <= -5  then '2. 5-10 days early'
        when days_late <= 0   then '3. 0-5 days early'
        when days_late <= 3   then '4. 0-3 days late'
        when days_late <= 7   then '5. 3-7 days late'
        when days_late <= 14  then '6. 7-14 days late'
        else '7. 14+ days late'
    end                          as delivery_bucket,
    count(*)                     as orders,
    avg(review_score)            as avg_review,
    avg((review_score = 1)::int) as one_star_rate,
    avg((review_score = 5)::int) as five_star_rate
from {{ ref('fct_orders') }}
where order_status = 'delivered' and review_score is not null and days_late is not null
group by 1
order by 1
