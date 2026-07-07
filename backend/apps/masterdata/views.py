from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DimBrand
from .serializers import DimBrandSerializer


class BrandListView(APIView):
    """Active brands, for the frontend's brand selector -- the one piece of
    filter-bar metadata that isn't itself an attribute_registry entry
    (brand is the tenant-scoping dimension every other filter/query is
    already keyed by, not one more optional filter)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        brands = DimBrand.objects.filter(active=True).order_by("brand_name")
        return Response({"brands": DimBrandSerializer(brands, many=True).data})
