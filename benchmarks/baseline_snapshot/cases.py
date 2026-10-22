"""Benchmark cases: small repositories with one known bug each (ground truth included).

Every case is a plain dict. The relevant modules are hand-written; the same unrelated 'filler'
modules are added to every case so retrieval has something to ignore. The bugs were written by
the RepoMedic author (not drawn from real projects), which is a limitation noted in the README.
"""
from __future__ import annotations

TEST_HEADER = (
    "import sys, pathlib\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
)

# ---------------------------------------------------------------- unrelated filler modules
_FILLER_DOMAINS = {
    "inventory": ("sku", "quantity"),
    "labels": ("destination", "weight"),
    "accounts": ("email", "plan"),
    "notifications": ("channel", "message"),
    "auditlog": ("actor", "action"),
    "exports": ("format", "rows"),
    "search_index": ("term", "document"),
    "scheduling": ("slot", "owner"),
}


def _filler(domain: str, key_a: str, key_b: str) -> str:
    return f'''"""{domain.replace("_", " ").title()} helpers."""
from collections import Counter


def normalise_{domain}(records):
    """Drop empty records and strip whitespace from string fields."""
    cleaned = []
    for record in records:
        if not record:
            continue
        cleaned.append({{k: (v.strip() if isinstance(v, str) else v) for k, v in record.items()}})
    return cleaned


def count_by_{key_a}(records):
    return Counter(record.get("{key_a}", "unknown") for record in records)


def summarise_{domain}(records):
    records = normalise_{domain}(records)
    return {{
        "records": len(records),
        "distinct_{key_a}": len(count_by_{key_a}(records)),
        "missing_{key_b}": sum(1 for r in records if not r.get("{key_b}")),
    }}


def filter_{domain}(records, predicate):
    return [record for record in normalise_{domain}(records) if predicate(record)]


def latest_{domain}(records, limit=5):
    return list(reversed(normalise_{domain}(records)))[:limit]
'''


FILLER_FILES = {f"{d}.py": _filler(d, a, b) for d, (a, b) in _FILLER_DOMAINS.items()}

# ---------------------------------------------------------------- cases
CASES: list[dict] = []

CASES.append({
    "name": "price_thousands_separator",
    "bug": "The cart total crashes with a ValueError when a price contains a thousands separator like '$1,299.00'.",
    "files": {
        "pricing.py": '''"""Price parsing helpers."""


def parse_price(text):
    """Convert a price string such as '$12.50' into a float."""
    return float(text.strip("$"))


def line_total(price_text, quantity):
    return parse_price(price_text) * quantity
''',
        "cart.py": '''"""Shopping cart totals."""
from pricing import line_total


def cart_total(lines):
    return round(sum(line_total(price, qty) for price, qty in lines), 2)
''',
        "checkout.py": '''"""Checkout summary."""
from cart import cart_total


def checkout_summary(lines):
    total = cart_total(lines)
    return {"items": len(lines), "total": total}
''',
        "tests/test_cart.py": TEST_HEADER + '''from cart import cart_total
from checkout import checkout_summary


def test_simple_prices():
    assert cart_total([("$5.00", 2), ("$1.50", 1)]) == 11.5


def test_checkout_summary_counts_items():
    assert checkout_summary([("$2.00", 3)]) == {"items": 1, "total": 6.0}


def test_thousands_separator():
    assert cart_total([("$1,299.00", 1), ("$5.00", 2)]) == 1309.0
''',
    },
    "bug_file": "pricing.py",
    "bug_function": "parse_price",
    "relevant_files": ["pricing.py", "cart.py", "checkout.py"],
    "diagnosis_keywords": ["comma", "thousand", "separator", ","],
    "reference_edits": [{"file": "pricing.py", "old": 'text.strip("$")', "new": 'text.strip("$").replace(",", "")'}],
})

CASES.append({
    "name": "pagination_off_by_one",
    "bug": "Requesting page 1 of a listing skips the first page of results and returns items from the second page.",
    "files": {
        "paging.py": '''"""Pagination helpers. Pages are numbered from 1."""


def page_bounds(page, size):
    start = page * size
    return start, start + size
''',
        "listing.py": '''"""Listing views."""
from paging import page_bounds


def list_page(items, page, size):
    start, end = page_bounds(page, size)
    return items[start:end]
''',
        "api.py": '''"""Request handlers."""
from listing import list_page


def handle_request(params, items):
    page = int(params.get("page", 1))
    size = int(params.get("size", 10))
    return {"page": page, "results": list_page(items, page, size)}
''',
        "tests/test_paging.py": TEST_HEADER + '''from api import handle_request


ITEMS = list(range(1, 26))


def test_second_page():
    assert handle_request({"page": "2", "size": "10"}, ITEMS)["results"] == list(range(11, 21))


def test_response_echoes_page_number():
    assert handle_request({"page": "3", "size": "10"}, ITEMS)["page"] == 3


def test_first_page_starts_at_first_item():
    assert handle_request({"page": "1", "size": "10"}, ITEMS)["results"] == list(range(1, 11))
''',
    },
    "bug_file": "paging.py",
    "bug_function": "page_bounds",
    "relevant_files": ["paging.py", "listing.py", "api.py"],
    "diagnosis_keywords": ["off-by-one", "off by one", "page - 1", "page-1", "1-based", "zero", "start", "numbered from 1"],
    "reference_edits": [{"file": "paging.py", "old": "start = page * size", "new": "start = (page - 1) * size"}],
})

CASES.append({
    "name": "free_shipping_boundary",
    "bug": "Orders of exactly $75 should ship free, but customers with a $75.00 subtotal are still charged shipping.",
    "files": {
        "fees.py": '''"""Shipping fee rules: orders of $75 or more ship free."""

FREE_SHIPPING_THRESHOLD = 75
FLAT_SHIPPING_FEE = 5


def shipping_fee(subtotal):
    if subtotal > FREE_SHIPPING_THRESHOLD:
        return 0
    return FLAT_SHIPPING_FEE
''',
        "orders.py": '''"""Order totals."""
from fees import shipping_fee


def order_total(prices):
    subtotal = sum(prices)
    return round(subtotal + shipping_fee(subtotal), 2)
''',
        "invoice.py": '''"""Invoice rendering."""
from orders import order_total


def render_invoice(prices):
    return f"Total due: ${order_total(prices):.2f}"
''',
        "tests/test_fees.py": TEST_HEADER + '''from orders import order_total
from invoice import render_invoice


def test_small_order_pays_shipping():
    assert order_total([20.0, 10.0]) == 35.0


def test_large_order_ships_free():
    assert order_total([60.0, 30.0]) == 90.0


def test_invoice_text():
    assert render_invoice([100.0]) == "Total due: $100.00"


def test_exactly_threshold_ships_free():
    assert order_total([75.0]) == 75.0
''',
    },
    "bug_file": "fees.py",
    "bug_function": "shipping_fee",
    "relevant_files": ["fees.py", "orders.py", "invoice.py"],
    "diagnosis_keywords": [">=", "boundary", "greater than or equal", "inclusive", "exactly", "equal"],
    "reference_edits": [{"file": "fees.py", "old": "subtotal > FREE_SHIPPING_THRESHOLD", "new": "subtotal >= FREE_SHIPPING_THRESHOLD"}],
})

CASES.append({
    "name": "mutable_default_argument",
    "bug": "Tagging one product also adds the tag to every other product that was tagged without an existing list.",
    "files": {
        "tags.py": '''"""Tag helpers."""


def add_tag(tag, tags=[]):
    tags.append(tag)
    return tags
''',
        "catalog.py": '''"""Product catalog."""
from tags import add_tag


def tag_product(name, tag, existing=None):
    return {"name": name, "tags": add_tag(tag, existing) if existing is not None else add_tag(tag)}
''',
        "tests/test_tags.py": TEST_HEADER + '''from catalog import tag_product


def test_existing_tags_are_extended():
    assert tag_product("mug", "new", ["a"])["tags"] == ["a", "new"]


def test_products_do_not_share_tags():
    first = tag_product("mug", "kitchen")
    second = tag_product("pen", "office")
    assert first["tags"] == ["kitchen"]
    assert second["tags"] == ["office"]
''',
    },
    "bug_file": "tags.py",
    "bug_function": "add_tag",
    "relevant_files": ["tags.py", "catalog.py"],
    "diagnosis_keywords": ["mutable", "default argument", "default value", "shared", "tags=[]", "none"],
    "reference_edits": [{
        "file": "tags.py",
        "old": "def add_tag(tag, tags=[]):\n    tags.append(tag)",
        "new": "def add_tag(tag, tags=None):\n    if tags is None:\n        tags = []\n    tags.append(tag)",
    }],
})

CASES.append({
    "name": "moving_average_window",
    "bug": "The moving average drops the final window: a series of 5 values with window 3 should give 3 averages but gives 2.",
    "files": {
        "stats.py": '''"""Statistics helpers."""


def moving_average(values, window):
    averages = []
    for i in range(len(values) - window):
        chunk = values[i:i + window]
        averages.append(sum(chunk) / window)
    return averages
''',
        "trends.py": '''"""Trend summaries."""
from stats import moving_average


def trend_summary(values, window=3):
    averages = moving_average(values, window)
    return {"points": len(averages), "latest": averages[-1] if averages else None}
''',
        "dashboard.py": '''"""Dashboard data."""
from trends import trend_summary


def dashboard_row(name, values):
    return {"name": name, **trend_summary(values)}
''',
        "tests/test_stats.py": TEST_HEADER + '''from dashboard import dashboard_row
from stats import moving_average


def test_short_series_has_no_averages():
    assert moving_average([1, 2], 3) == []


def test_dashboard_row_name():
    assert dashboard_row("cpu", [1, 2, 3, 4])["name"] == "cpu"


def test_moving_average_includes_last_window():
    assert moving_average([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]


def test_trend_latest_value():
    assert dashboard_row("cpu", [1, 2, 3, 4, 5])["latest"] == 4.0
''',
    },
    "bug_file": "stats.py",
    "bug_function": "moving_average",
    "relevant_files": ["stats.py", "trends.py", "dashboard.py"],
    "diagnosis_keywords": ["range", "len(values) - window", "off-by-one", "off by one", "+ 1", "last window", "final window"],
    "reference_edits": [{"file": "stats.py", "old": "range(len(values) - window)", "new": "range(len(values) - window + 1)"}],
})

CASES.append({
    "name": "shallow_config_merge",
    "bug": "Overriding one nested setting (for example database.port) removes the other nested defaults such as database.host.",
    "files": {
        "config.py": '''"""Configuration merging."""


def merge_config(base, override):
    result = dict(base)
    result.update(override)
    return result
''',
        "loader.py": '''"""Settings loader."""
from config import merge_config

DEFAULTS = {"debug": False, "database": {"host": "localhost", "port": 5432}}


def load_settings(user_settings):
    return merge_config(DEFAULTS, user_settings)
''',
        "tests/test_config.py": TEST_HEADER + '''from loader import load_settings


def test_top_level_override():
    assert load_settings({"debug": True})["debug"] is True


def test_defaults_are_kept():
    assert load_settings({})["database"] == {"host": "localhost", "port": 5432}


def test_nested_override_keeps_sibling_defaults():
    merged = load_settings({"database": {"port": 6000}})
    assert merged["database"] == {"host": "localhost", "port": 6000}
''',
    },
    "bug_file": "config.py",
    "bug_function": "merge_config",
    "relevant_files": ["config.py", "loader.py"],
    "diagnosis_keywords": ["shallow", "nested", "deep", "recursive", "update", "overwrite"],
    "reference_edits": [{
        "file": "config.py",
        "old": "    result = dict(base)\n    result.update(override)\n    return result",
        "new": "    result = dict(base)\n    for key, value in override.items():\n        if isinstance(value, dict) and isinstance(result.get(key), dict):\n            result[key] = merge_config(result[key], value)\n        else:\n            result[key] = value\n    return result",
    }],
})


def build_case(case: dict, destination) -> None:
    """Write a case's files plus the shared filler modules into `destination`."""
    from pathlib import Path

    root = Path(destination)
    for relative, content in {**FILLER_FILES, **case["files"]}.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
