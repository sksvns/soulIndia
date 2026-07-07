from rest_framework import serializers

from .models import DimBrand


class DimBrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimBrand
        fields = ["brand_code", "brand_name"]
