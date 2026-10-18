-- The raw file has duplicate review_ids and some orders with several reviews.
-- Keep the most recently answered review per order (one row per order).
with ranked as (
    select
        review_id,
        order_id,
        review_score,
        review_comment_message is not null and length(trim(review_comment_message)) > 0 as has_comment,
        cast(review_creation_date as timestamp)   as review_created_at,
        cast(review_answer_timestamp as timestamp) as review_answered_at,
        row_number() over (partition by order_id order by review_answer_timestamp desc, review_id) as rn
    from {{ source('olist', 'olist_order_reviews_dataset') }}
)
select * exclude (rn) from ranked where rn = 1
