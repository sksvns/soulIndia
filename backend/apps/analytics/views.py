from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.masterdata.models import DimBrand

from . import cache, queries


def _resolve_brand(request) -> DimBrand:
    brand_code = request.query_params.get("brand_code", "")
    return get_object_or_404(DimBrand, brand_code=brand_code.upper(), active=True)


def _int_or_none(value):
    return int(value) if value not in (None, "") else None


class DashboardSummaryView(APIView):
    """Total/MRP/Net sales + total discount, broken down by season."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand = _resolve_brand(request)
        financial_year = request.query_params.get("financial_year") or None
        month_no = _int_or_none(request.query_params.get("month"))

        filters = {"financial_year": financial_year, "month_no": month_no}
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "dashboard_summary",
            filters,
            lambda: queries.dashboard_summary(brand.brand_id, financial_year, month_no),
        )
        return Response({**data, "brand_code": brand.brand_code, "cache_hit": cache_hit})


class StorePerfView(APIView):
    """Top-10 stores, orderable by net/mrp/quantity/discount_pct."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand = _resolve_brand(request)
        financial_year = request.query_params.get("financial_year") or None
        month_no = _int_or_none(request.query_params.get("month"))
        order_by = request.query_params.get("order_by", "net")

        filters = {"financial_year": financial_year, "month_no": month_no, "order_by": order_by}
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "store_perf_top10",
            filters,
            lambda: queries.store_perf_top10(brand.brand_id, financial_year, month_no, order_by),
        )
        return Response({"results": data, "brand_code": brand.brand_code, "cache_hit": cache_hit})


class CategoryPerfView(APIView):
    """Top-10 category/sub_category, optional store multi-select."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brand = _resolve_brand(request)
        financial_year = request.query_params.get("financial_year") or None
        month_no = _int_or_none(request.query_params.get("month"))
        order_by = request.query_params.get("order_by", "net")
        store_ids_param = request.query_params.get("store_ids")
        store_ids = [int(s) for s in store_ids_param.split(",")] if store_ids_param else None

        filters = {
            "financial_year": financial_year,
            "month_no": month_no,
            "order_by": order_by,
            "store_ids": store_ids,
        }
        data, cache_hit = cache.get_or_compute(
            brand.brand_id,
            "category_perf_top10",
            filters,
            lambda: queries.category_perf_top10(
                brand.brand_id, financial_year, month_no, store_ids, order_by
            ),
        )
        return Response({"results": data, "brand_code": brand.brand_code, "cache_hit": cache_hit})
