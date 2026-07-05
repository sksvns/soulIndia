from django.shortcuts import get_object_or_404
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


def _resolve_brand(request) -> DimBrand:
    brand_code = request.query_params.get("brand_code", "")
    return get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)


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


class FilterOptionsView(APIView):
    """Metadata for the frontend filter bar, read live from
    attribute_registry -- a new filterable attribute shows up here as soon
    as it's a registry row, no frontend/backend code change required for
    the frontend to *discover* it (whether it's wired into a given MV yet
    is a separate, independent question the filter engine handles
    gracefully either way)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        attributes = list(
            AttributeRegistry.objects.filter(active=True, is_filterable=True)
            .order_by("canonical_name")
            .values("canonical_name", "source", "is_dimension", "data_type")
        )
        return Response({"filters": attributes})


class DashboardSummaryView(APIView):
    """Total/MRP/Net sales + total discount, broken down by season."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand = _resolve_brand(request)
        filters = _parse_filters(request)
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "dashboard_summary",
            filters,
            lambda: queries.dashboard_summary(brand.brand_id, filters),
        )
        return Response({**data, "brand_code": brand.brand_code, "cache_hit": cache_hit})


class StorePerfView(APIView):
    """Top-10 stores, orderable by net/mrp/quantity/discount_pct."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand = _resolve_brand(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "store_perf_top10",
            {**filters, "order_by": order_by},
            lambda: queries.store_perf_top10(brand.brand_id, filters, order_by),
        )
        return Response({"results": data, "brand_code": brand.brand_code, "cache_hit": cache_hit})


class CategoryPerfView(APIView):
    """Top-10 category/sub_category, optional store multi-select."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand = _resolve_brand(request)
        filters = _parse_filters(request)
        order_by = request.query_params.get("order_by", "net")
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "category_perf_top10",
            {**filters, "order_by": order_by},
            lambda: queries.category_perf_top10(brand.brand_id, filters, order_by),
        )
        return Response({"results": data, "brand_code": brand.brand_code, "cache_hit": cache_hit})


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

    def get(self, request):
        brand = _resolve_brand(request)
        dimension, metric, error = _validate_trend_params(request)
        if error:
            return error
        store_code = request.query_params.get("store")

        cache_filters = {"dimension": dimension, "metric": metric, "store": store_code}
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "store_trend",
            cache_filters,
            lambda: queries.store_trend(brand.brand_id, dimension, metric, store_code),
        )
        return Response({"results": data, "brand_code": brand.brand_code, "cache_hit": cache_hit})


class CategoryTrendView(APIView):
    """A category's (optionally sub_category's) performance over time,
    optionally scoped to one or more stores."""

    permission_classes = [IsAuthenticated]

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
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "category_trend",
            cache_filters,
            lambda: queries.category_trend(
                brand.brand_id, dimension, metric, category, sub_category, store_codes
            ),
        )
        return Response({"results": data, "brand_code": brand.brand_code, "cache_hit": cache_hit})
