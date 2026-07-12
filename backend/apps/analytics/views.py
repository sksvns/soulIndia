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
# Dashboard-only: brand is optional there (client feedback -- it defaults
# to every active brand combined), unlike every other analytics endpoint.
DASHBOARD_BRAND_CODE_PARAM = OpenApiParameter(
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
DASHBOARD_FILTER_PARAMS = [DASHBOARD_BRAND_CODE_PARAM, *FILTER_PARAMS[1:]]
ORDER_BY_PARAM = OpenApiParameter(
    "order_by",
    str,
    enum=["net", "mrp", "quantity", "discount_pct"],
    description="default: net",
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


def _resolve_dashboard_brand_ids(request) -> tuple[list[int], str | None]:
    """Dashboard-only: brand_code is optional, defaulting to every active
    brand combined (client feedback). Returns (brand_ids, brand_code) --
    brand_code is None when no specific brand was requested, so the
    response can honestly report "no single brand" rather than an
    arbitrary one."""
    brand_code = request.query_params.get("brand_code", "")
    if not brand_code:
        brand_ids = list(DimBrand.objects.filter(active=True).values_list("brand_id", flat=True))
        return brand_ids, None
    brand = get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)
    return [brand.brand_id], brand.brand_code


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
    """Total/MRP/Net sales + total discount, broken down by financial
    year. brand_code is optional -- omitted means every active brand
    combined (client feedback: that's the dashboard's default view, with
    brand as a filter to narrow down from there, not a precondition)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*DASHBOARD_FILTER_PARAMS, REFRESH_PARAM])
    def get(self, request):
        brand_ids, brand_code = _resolve_dashboard_brand_ids(request)
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

    @extend_schema(parameters=[DASHBOARD_BRAND_CODE_PARAM])
    def get(self, request):
        brand_ids, _ = _resolve_dashboard_brand_ids(request)
        return Response(queries.dashboard_filter_options(brand_ids))


class StorePerfView(APIView):
    """Top-10 stores, orderable by net/mrp/quantity/discount_pct."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*FILTER_PARAMS, ORDER_BY_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand = _resolve_brand(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        data, cache_hit, cached_at = cache.get_or_compute(
            brand.brand_id,
            "store_perf_top10",
            {**filters, "order_by": order_by},
            lambda: queries.store_perf_top10(brand.brand_id, filters, order_by),
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


class CategoryPerfView(APIView):
    """Top-10 category/sub_category, optional store multi-select."""

    permission_classes = [IsAuthenticated]

    @extend_schema(parameters=[*FILTER_PARAMS, ORDER_BY_PARAM, REFRESH_PARAM])
    def get(self, request):
        brand = _resolve_brand(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        data, cache_hit, cached_at = cache.get_or_compute(
            brand.brand_id,
            "category_perf_top10",
            {**filters, "order_by": order_by},
            lambda: queries.category_perf_top10(brand.brand_id, filters, order_by),
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
