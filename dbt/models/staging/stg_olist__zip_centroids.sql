-- 1M geolocation rows -> one centroid per zip prefix. Points outside Brazil's
-- bounding box are recording errors and are dropped before taking the median.
select
    {{ zip_prefix('geolocation_zip_code_prefix') }} as zip_prefix,
    median(geolocation_lat) as lat,
    median(geolocation_lng) as lng,
    count(*)                as n_points
from {{ source('olist', 'olist_geolocation_dataset') }}
where geolocation_lat between -34 and 6
  and geolocation_lng between -74 and -34
group by 1
