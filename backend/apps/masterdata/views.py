from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BrandUploadConfig, DimBrand
from .serializers import BrandUploadConfigSerializer, DimBrandSerializer


class BrandListView(APIView):
    """Active brands, for the frontend's brand selector -- the one piece of
    filter-bar metadata that isn't itself an attribute_registry entry
    (brand is the tenant-scoping dimension every other filter/query is
    already keyed by, not one more optional filter)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brands = DimBrand.objects.filter(active=True).order_by("brand_name")
        return Response({"brands": DimBrandSerializer(brands, many=True).data})


class UploadConfigListView(APIView):
    """Active (brand, product_line) pairs, for the upload screen's brand +
    product line selection -- a brand with more than one product line
    (e.g. a future womenswear file alongside an existing menswear one)
    needs the user to pick which mapping config applies, and that list
    must come from the database, never be hardcoded in the frontend."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        configs = BrandUploadConfig.objects.filter(active=True, brand__active=True).select_related(
            "brand"
        )
        return Response({"upload_configs": BrandUploadConfigSerializer(configs, many=True).data})
