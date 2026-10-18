{# Generic test: fails when more than max_share of rows match the condition (a tolerance check, not a hard rule). #}
{% test row_share_below(model, condition, max_share) %}
with s as (
    select avg(case when {{ condition }} then 1.0 else 0.0 end) as share from {{ model }}
)
select * from s where share > {{ max_share }}
{% endtest %}
