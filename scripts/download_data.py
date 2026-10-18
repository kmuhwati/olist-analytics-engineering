"""Download the Olist Brazilian e-commerce public dataset (9 CSVs, ~126 MB).

Source: Olist's own repository https://github.com/olist/work-at-olist-data
(the same files as Kaggle's olistbr/brazilian-ecommerce; CC BY-NC-SA 4.0).
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets"
FILES = [
    "olist_customers_dataset", "olist_geolocation_dataset", "olist_order_items_dataset",
    "olist_order_payments_dataset", "olist_order_reviews_dataset", "olist_orders_dataset",
    "olist_products_dataset", "olist_sellers_dataset", "product_category_name_translation",
]
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest = RAW / f"{name}.csv"
        if not dest.exists():
            urllib.request.urlretrieve(f"{BASE}/{name}.csv", dest)
        rows = sum(1 for _ in dest.open("rb")) - 1
        print(f"{name}: {rows:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
