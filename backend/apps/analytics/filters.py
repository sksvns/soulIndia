"""Composable filter engine driven by attribute_registry (plan.md Day 8): a
new filterable attribute becomes a registry row + an entry here, never a
rewrite of the query functions in queries.py.

MV_COLUMNS declares which canonical attributes each materialized view can
actually filter on -- not every attribute applies to every MV by design.
A filter for an attribute the target MV doesn't support is silently
dropped rather than erroring, since asking "top categories" to also
filter by store is a perfectly normal, supported combination, while
asking a coarser-grained view to filter by something outside its grain
is simply outside what that view can answer -- the caller already chose
which MV/endpoint to query, so this isn't a request to reject, it's a
no-op for that one filter.

`brand` is deliberately not listed here: it's always required and resolved
to brand_id before reaching the filter engine (apps.analytics.views), never
optional like the rest of these.

Deliberately unsupported for now: color, fit, size, article_code -- see
migration 0002's docstring for why (cardinality; no current view needs
them). They remain valid attribute_registry entries -- adding a column for
them to the right MV, plus one more entry here, is the only change needed
to make them filterable, not a query rewrite.
"""

MV_COLUMNS = {
    "mv_store_perf": {
        "store": "store_code",
        "city": "city",
        "zone": "zone",
        "financial_year": "financial_year",
        "month": "month_no",
        "season": "season_code",
        "discount_range": "discount_bucket",
    },
    "mv_category_perf": {
        "store": "store_code",
        "category": "category",
        "sub_category": "sub_category",
        "gender": "gender",
        "financial_year": "financial_year",
        "month": "month_no",
        "season": "season_code",
        "discount_range": "discount_bucket",
    },
    # Same table as mv_category_perf, but for the Dashboard's own queries
    # only (queries._dashboard_yearly_breakdown/_dashboard_monthly_
    # breakdown) -- store filters by store_name here, not store_code.
    # store_code is only unique *within* a brand (each brand assigns its
    # own), while the Dashboard can show every active brand combined
    # (client feedback), so the same physical store shows up once per
    # brand under a different code; store_name is what the client
    # actually confirmed is stable/unique per store within a brand and
    # shared across brands for the same real-world location. Every other
    # page (Stores/Categories/Trends) is always scoped to one brand, where
    # store_name and store_code are already 1:1 -- this split only matters
    # for the one view that can span brands.
    "dashboard_category_perf": {
        "store": "store_name",
        "category": "category",
        "sub_category": "sub_category",
        "gender": "gender",
        "financial_year": "financial_year",
        "month": "month_no",
        "season": "season_code",
        "discount_range": "discount_bucket",
    },
    # Not a materialized view -- the one deliberate exception (see
    # queries._dashboard_weekly_breakdown's docstring). financial_year/month
    # aren't listed here because that query pins those via dim_calendar
    # directly rather than through this generic filter engine; this entry
    # only covers the filters that can still narrow a single brand-month
    # further (category/sub_category/store), joined in from dim_product/
    # dim_store. store filters by name for the same reason as
    # dashboard_category_perf above.
    "fact_sales": {
        "store": "st.store_name",
        "category": "p.category",
        "sub_category": "p.sub_category",
        "gender": "p.gender",
    },
}


def build_where(mv_name: str, filters: dict) -> tuple[str, dict]:
    """filters: canonical_name -> scalar value, or a list for an IN-style
    match (e.g. store multi-select). Returns (sql_fragment, params); the
    fragment is "" (safe to concatenate) if no filters applied."""
    columns = MV_COLUMNS.get(mv_name, {})
    clauses = []
    params = {}
    for canonical_name, value in (filters or {}).items():
        if value in (None, "", []):
            continue
        column = columns.get(canonical_name)
        if not column:
            continue
        param_name = f"filter_{canonical_name}"
        if isinstance(value, (list, tuple, set)):
            clauses.append(f"{column} = ANY(%({param_name})s)")
            params[param_name] = list(value)
        else:
            clauses.append(f"{column} = %({param_name})s")
            params[param_name] = value
    return " AND ".join(clauses), params
