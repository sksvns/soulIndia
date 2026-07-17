from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.masterdata.models import AttributeRegistry, DimBrand

from . import cache, queries
from .queries import METRIC_COLUMNS, TREND_DIMENSIONS

# Query param name -> whether comma-separated values mean a multi-select
# (IN-style) filter. Names match attribute_registry.canonical_name exactly,
# so a new filterable attribute is "add a registry row + an MV_COLUMNS
# entry" (apps.analytics.filters), never a change here.
FILTER_PARAM_NAMES = [
    "financial_year",
    "month",
    "season",
    "store",
    "city",
    "zone",
    "category",
    "sub_category",
    "gender",
    "discount_range",
]
MULTI_VALUE_PARAMS = {"store", "discount_range"}

BRAND_CODE_PARAM = OpenApiParameter(
    "brand_code", str, required=True, description="e.g. KILLER, PEPE"
)
# Dashboard and Stores only: brand is optional there (client feedback --
# both default to every active brand combined), unlike Categories/Trends,
# which still require exactly one.
OPTIONAL_BRAND_CODE_PARAM = OpenApiParameter(
    "brand_code",
    str,
    required=False,
    description="e.g. KILLER, PEPE; omitted means every active brand combined",
)
FILTER_PARAMS = [
    BRAND_CODE_PARAM,
    OpenApiParameter("financial_year", str, description="e.g. 23-24"),
    OpenApiParameter("month", int, description="1-12 (calendar month)"),
    OpenApiParameter("season", str, description="e.g. SS23, AW23"),
    OpenApiParameter("store", str, description="store_code; comma-separated for multi-select"),
    OpenApiParameter("city", str),
    OpenApiParameter("zone", str),
    OpenApiParameter("category", str),
    OpenApiParameter("sub_category", str),
    OpenApiParameter("gender", str),
    OpenApiParameter(
        "discount_range", str, description="bucket label; comma-separated for multi-select"
    ),
]
OPTIONAL_BRAND_FILTER_PARAMS = [OPTIONAL_BRAND_CODE_PARAM, *FILTER_PARAMS[1:]]
ORDER_BY_PARAM = OpenApiParameter(
    "order_by",
    str,
    enum=["net", "mrp", "quantity", "discount_pct"],
    description="default: net",
)
PAGE_SIZES = {"10": 10, "20": 20, "50": 50, "100": 100, "200": 200, "all": None}
PAGE_PARAM = OpenApiParameter("page", int, description="1-indexed page number; default 1")
PAGE_SIZE_PARAM = OpenApiParameter(
    "page_size", str, enum=sorted(PAGE_SIZES), description="default: 10"
)
DIMENSION_PARAM = OpenApiParameter(
    "dimension",
    str,
    enum=sorted(TREND_DIMENSIONS),
    description="default: month",
)
METRIC_PARAM = OpenApiParameter(
    "metric", str, enum=sorted(METRIC_COLUMNS), description="default: net"
)


def _resolve_brand(request) -> DimBrand:
    brand_code = request.query_params.get("brand_code", "")
    return get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)


def _resolve_optional_brand_ids(request) -> tuple[list[int], str | None]:
    """Dashboard and Stores: brand_code is optional, defaulting to every
    active brand combined (client feedback). Returns (brand_ids,
    brand_code) -- brand_code is None when no specific brand was
    requested, so the response can honestly report "no single brand"
    rather than an arbitrary one."""
    brand_code = request.query_params.get("brand_code", "")
    if not brand_code:
        brand_ids = list(DimBrand.objects.filter(active=True).values_list("brand_id", flat=True))
        return brand_ids, None
    brand = get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)
    return [brand.brand_id], brand.brand_code


def _parse_pagination(request) -> tuple[int | None, int, int, Response | None]:
    """Returns (limit, offset, page, error_response). page_size is a
    fixed 10/20/50/100/200/all choice (client feedback), not an arbitrary
    integer -- limit=None for "all" skips LIMIT/OFFSET entirely rather
    than passing some large sentinel number through to SQL."""
    page_size_param = request.query_params.get("page_size", "10")
    if page_size_param not in PAGE_SIZES:
        return (
            None,
            None,
            None,
            Response(
                {"detail": f"page_size must be one of {sorted(PAGE_SIZES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            ),
        )
    limit = PAGE_SIZES[page_size_param]
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        return (
            None,
            None,
            None,
            Response({"detail": "page must be an integer"}, status=status.HTTP_400_BAD_REQUEST),
        )
    offset = (page - 1) * limit if limit is not None else 0
    return limit, offset, page, None


def _parse_filters(request) -> dict:
    filters = {}
    for name in FILTER_PARAM_NAMES:
        raw = request.query_params.get(name)
        if not raw:
            continue
        filters[name] = raw.split(",") if name in MULTI_VALUE_PARAMS and "," in raw else raw
    if "month" in filters:
        filters["month"] = int(filters["month"])
    return filters


def _force_refresh(request) -> bool:
    return request.query_params.get("refresh", "").lower() == "true"


REFRESH_PARAM = OpenApiParameter(
    "refresh",
    bool,
    description="true bypasses the cache and recomputes from the database",
)


class FilterOptionsView(APIView):
    """Metadata for the frontend filter bar, read live from
    attribute_registry -- a new filterable attribute shows up here as soon
    as it's a registry row, no frontend/backend code change required for
    the frontend to *discover* it (whether it's wired into a given MV yet
    is a separate, independent question the filter engine handles
    gracefully either way)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[])
    def get(self, request):
        attributes = list(
            AttributeRegistry.objects.filter(active=True, is_filterable=True)
            .order_by("canonical_name")
            .values("canonical_name", "source", "is_dimension", "data_type")
        )
        return Response({"filters": attributes})


class DashboardSummaryView(APIView):
    """Total/MRP/Net sales + total discount, broken down at a granularity
    that adapts to the filter selection -- year by default, month once a
    single year is picked, week once that year is narrowed to a single
    month too (client feedback). brand_code is optional -- omitted means
    every active brand combined (client feedback: that's the dashboard's
    default view, with brand as a filter to narrow down from there, not a
    precondition)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        if brand_code:
            # One specific brand -- the regular cache-aside path.
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "dashboard_summary",
                filters,
                lambda: queries.dashboard_summary(brand_ids, filters),
                force_refresh=_force_refresh(request),
            )
        else:
            # All brands combined: cheap enough (a handful of brands, the
            # same indexed view every other dashboard query already
            # hits) to always compute fresh, rather than adding a second
            # cache-invalidation path that no single brand's upload
            # would know on its own to bust.
            data = queries.dashboard_summary(brand_ids, filters)
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {**data, "brand_code": brand_code, "cache_hit": cache_hit, "cached_at": cached_at}
        )


class DashboardFilterOptionsView(APIView):
    """Distinct financial years/categories/sub_categories/stores actually
    present in the relevant data (one brand, or every active brand
    combined when brand_code is omitted), for populating the Dashboard's
    own filter dropdowns (a simplified 6-field set -- brand/year/month/
    category/sub_category/store -- per client feedback, separate from the
    full filter bar the other analytics pages still use)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OPTIONAL_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_optional_brand_ids(request)
        return Response(queries.dashboard_filter_options(brand_ids))


class StorePerfView(APIView):
    """Every store matching the filters, ranked by net/mrp/quantity/
    discount_pct, paged server-side (client feedback: page size is a
    10/20/50/100/200/all choice, default 10 -- sorting always applies to
    the complete result before paging, never just whichever page is
    currently loaded). brand_code is optional -- omitted means every
    active brand combined, same convention as the Dashboard."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            *OPTIONAL_BRAND_FILTER_PARAMS,
            ORDER_BY_PARAM,
            PAGE_PARAM,
            PAGE_SIZE_PARAM,
            REFRESH_PARAM,
        ]
    )
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        limit, offset, page, error = _parse_pagination(request)
        if error:
            return error
        page_size_param = request.query_params.get("page_size", "10")

        cache_filters = {
            **filters,
            "order_by": order_by,
            "page": page,
            "page_size": page_size_param,
        }

        def compute():
            return queries.store_perf(brand_ids, filters, order_by, limit, offset)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "store_perf",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        rows, total_count = data

        return Response(
            {
                "results": rows,
                "total_count": total_count,
                "page": page,
                "page_size": page_size_param,
                "brand_code": brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )


class StoreFilterOptionsView(APIView):
    """Distinct financial years actually present (one brand, or every
    active brand combined when brand_code is omitted), for the Stores
    page's own simplified filter bar (client feedback)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OPTIONAL_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_optional_brand_ids(request)
        return Response(queries.store_filter_options(brand_ids))


class CategoryPerfView(APIView):
    """Every category matching the filters, ranked by net/mrp/quantity/
    discount_pct (client feedback: no longer capped at a top-10 -- every
    category must be choosable on the Categories page's multi-select).
    brand_code is optional -- omitted means every active brand combined,
    same convention as the Dashboard/Stores."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, ORDER_BY_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        cache_filters = {**filters, "order_by": order_by}

        def compute():
            return queries.category_ranking(brand_ids, filters, order_by)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "category_ranking",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {
                "results": data,
                "brand_code": brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )


class CategoryFilterOptionsView(APIView):
    """Distinct financial years/store names actually present (one brand,
    or every active brand combined when brand_code is omitted), for the
    Categories page's own filter bar (client feedback: brand/year/month/
    store, same convention as the Dashboard's)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OPTIONAL_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_optional_brand_ids(request)
        return Response(queries.category_filter_options(brand_ids))


CATEGORIES_PARAM = OpenApiParameter(
    "categories", str, description="comma-separated category names to chart", required=True
)


class CategoryLineChartView(APIView):
    """Each requested category's own MRP/Net/Discount/Quantity broken
    down at a granularity that adapts to the filter selection -- year by
    default, month once a single year is picked, week once that year is
    narrowed to a single month too (client feedback, same as the
    Dashboard). brand_code is optional -- omitted means every active
    brand combined."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, CATEGORIES_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        categories_param = request.query_params.get("categories", "")
        categories = [c for c in categories_param.split(",") if c]
        cache_filters = {**filters, "categories": categories}

        def compute():
            return queries.category_line_chart(brand_ids, filters, categories)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "category_line_chart",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {**data, "brand_code": brand_code, "cache_hit": cache_hit, "cached_at": cached_at}
        )


class SubcategoryPerfView(APIView):
    """Every sub_category matching the filters, ranked by net/mrp/
    quantity/discount_pct -- same conventions as CategoryPerfView, one
    level finer (client feedback: a dedicated Subcategory page, exactly
    the same brand/year/month/store filter set, no extra Category
    filter)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, ORDER_BY_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        cache_filters = {**filters, "order_by": order_by}

        def compute():
            return queries.subcategory_ranking(brand_ids, filters, order_by)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "subcategory_ranking",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {
                "results": data,
                "brand_code": brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )


class SubcategoryFilterOptionsView(APIView):
    """Distinct financial years/store names for the Subcategory page's
    filter bar -- same convention as CategoryFilterOptionsView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OPTIONAL_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_optional_brand_ids(request)
        return Response(queries.subcategory_filter_options(brand_ids))


SUBCATEGORIES_PARAM = OpenApiParameter(
    "sub_categories", str, description="comma-separated sub_category names to chart", required=True
)


class SubcategoryLineChartView(APIView):
    """Each requested sub_category's own MRP/Net/Discount/Quantity broken
    down at a granularity that adapts to the filter selection -- same as
    CategoryLineChartView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, SUBCATEGORIES_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        subcategories_param = request.query_params.get("sub_categories", "")
        subcategories = [c for c in subcategories_param.split(",") if c]
        cache_filters = {**filters, "sub_categories": subcategories}

        def compute():
            return queries.subcategory_line_chart(brand_ids, filters, subcategories)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "subcategory_line_chart",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {**data, "brand_code": brand_code, "cache_hit": cache_hit, "cached_at": cached_at}
        )


class ColorPerfView(APIView):
    """Every color matching the filters, ranked by net/mrp/quantity/
    discount_pct -- same conventions as CategoryPerfView. filters may
    include "category" to narrow from every category combined to just
    one (client feedback: same "all, or narrow to one" pattern as
    brand)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, ORDER_BY_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        cache_filters = {**filters, "order_by": order_by}

        def compute():
            return queries.color_ranking(brand_ids, filters, order_by)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "color_ranking",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {
                "results": data,
                "brand_code": brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )


class ColorFilterOptionsView(APIView):
    """Distinct financial years/store names/categories for the Colors
    page's filter bar (brand/year/month/store + Category) -- same
    convention as CategoryFilterOptionsView, plus the category list."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OPTIONAL_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_optional_brand_ids(request)
        return Response(queries.color_filter_options(brand_ids))


COLORS_PARAM = OpenApiParameter(
    "colors", str, description="comma-separated color names to chart", required=True
)


class ColorLineChartView(APIView):
    """Each requested color's own MRP/Net/Discount/Quantity broken down
    at a granularity that adapts to the filter selection -- same as
    CategoryLineChartView. filters may include "category" to narrow the
    whole chart to one category."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, COLORS_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        colors_param = request.query_params.get("colors", "")
        colors = [c for c in colors_param.split(",") if c]
        cache_filters = {**filters, "colors": colors}

        def compute():
            return queries.color_line_chart(brand_ids, filters, colors)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "color_line_chart",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {**data, "brand_code": brand_code, "cache_hit": cache_hit, "cached_at": cached_at}
        )


class SizePerfView(APIView):
    """Every size matching the filters, ranked by net/mrp/quantity/
    discount_pct -- same conventions as ColorPerfView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, ORDER_BY_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        cache_filters = {**filters, "order_by": order_by}

        def compute():
            return queries.size_ranking(brand_ids, filters, order_by)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "size_ranking",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {
                "results": data,
                "brand_code": brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )


class SizeFilterOptionsView(APIView):
    """Distinct financial years/store names/categories for the Sizes
    page's filter bar -- same convention as ColorFilterOptionsView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[OPTIONAL_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_optional_brand_ids(request)
        return Response(queries.size_filter_options(brand_ids))


SIZES_PARAM = OpenApiParameter(
    "sizes", str, description="comma-separated size names to chart", required=True
)


class SizeLineChartView(APIView):
    """Each requested size's own MRP/Net/Discount/Quantity broken down at
    a granularity that adapts to the filter selection -- same as
    ColorLineChartView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*OPTIONAL_BRAND_FILTER_PARAMS, SIZES_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_optional_brand_ids(request)
        filters = _parse_filters(request)
        sizes_param = request.query_params.get("sizes", "")
        sizes = [c for c in sizes_param.split(",") if c]
        cache_filters = {**filters, "sizes": sizes}

        def compute():
            return queries.size_line_chart(brand_ids, filters, sizes)

        if brand_code:
            data, cache_hit, cached_at = cache.get_or_compute(
                brand_ids[0],
                "size_line_chart",
                cache_filters,
                compute,
                force_refresh=_force_refresh(request),
            )
        else:
            data = compute()
            cache_hit = False
            cached_at = timezone.now().isoformat()
        return Response(
            {**data, "brand_code": brand_code, "cache_hit": cache_hit, "cached_at": cached_at}
        )


def _validate_trend_params(request):
    dimension = request.query_params.get("dimension", "month")
    metric = request.query_params.get("metric", "net")
    if dimension not in TREND_DIMENSIONS:
        return (
            None,
            None,
            Response(
                {"detail": f"dimension must be one of {sorted(TREND_DIMENSIONS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            ),
        )
    if metric not in METRIC_COLUMNS:
        return (
            None,
            None,
            Response(
                {"detail": f"metric must be one of {sorted(METRIC_COLUMNS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            ),
        )
    return dimension, metric, None


class StoreTrendView(APIView):
    """A store's (or the whole brand's) performance over time: YoY
    (dimension=financial_year), MoM (dimension=month), or Season-by-Season
    (dimension=season), on net/mrp/quantity."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            BRAND_CODE_PARAM,
            DIMENSION_PARAM,
            METRIC_PARAM,
            OpenApiParameter("store", str, description="store_code; brand-wide if omitted"),
            REFRESH_PARAM,
        ]
    )
    def get(self, request):
        brand = _resolve_brand(request)
        dimension, metric, error = _validate_trend_params(request)
        if error:
            return error
        store_code = request.query_params.get("store")

        cache_filters = {"dimension": dimension, "metric": metric, "store": store_code}
        data, cache_hit, cached_at = cache.get_or_compute(
            brand.brand_id,
            "store_trend",
            cache_filters,
            lambda: queries.store_trend(brand.brand_id, dimension, metric, store_code),
            force_refresh=_force_refresh(request),
        )
        return Response(
            {
                "results": data,
                "brand_code": brand.brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )


class CategoryTrendView(APIView):
    """A category's (optionally sub_category's) performance over time,
    optionally scoped to one or more stores."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            BRAND_CODE_PARAM,
            DIMENSION_PARAM,
            METRIC_PARAM,
            OpenApiParameter("category", str),
            OpenApiParameter("sub_category", str),
            OpenApiParameter(
                "store", str, description="store_code(s), comma-separated; brand-wide if omitted"
            ),
            REFRESH_PARAM,
        ]
    )
    def get(self, request):
        brand = _resolve_brand(request)
        dimension, metric, error = _validate_trend_params(request)
        if error:
            return error
        category = request.query_params.get("category")
        sub_category = request.query_params.get("sub_category")
        store_param = request.query_params.get("store")
        store_codes = store_param.split(",") if store_param else None

        cache_filters = {
            "dimension": dimension,
            "metric": metric,
            "category": category,
            "sub_category": sub_category,
            "store_codes": store_codes,
        }
        data, cache_hit, cached_at = cache.get_or_compute(
            brand.brand_id,
            "category_trend",
            cache_filters,
            lambda: queries.category_trend(
                brand.brand_id, dimension, metric, category, sub_category, store_codes
            ),
            force_refresh=_force_refresh(request),
        )
        return Response(
            {
                "results": data,
                "brand_code": brand.brand_code,
                "cache_hit": cache_hit,
                "cached_at": cached_at,
            }
        )
