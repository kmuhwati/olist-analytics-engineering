{# Generic test: fails on rows where the SQL expression is false. #}
{% test expression_is_true(model, expression) %}
select * from {{ model }} where not ({{ expression }})
{% endtest %}
