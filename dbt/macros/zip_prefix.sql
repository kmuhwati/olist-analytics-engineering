{# Olist zip prefixes arrive as integers in some files and strings in others; normalise to 5-char text. #}
{% macro zip_prefix(col) -%}
    lpad(cast({{ col }} as varchar), 5, '0')
{%- endmacro %}
