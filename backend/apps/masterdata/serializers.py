from rest_framework import serializers

from .models import BrandUploadConfig, DimBrand


class DimBrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = DimBrand
        fields = ["brand_code", "brand_name"]


class BrandUploadConfigSerializer(serializers.ModelSerializer):
    brand_code = serializers.CharField(source="brand.brand_code")

    class Meta:
        model = BrandUploadConfig
        fields = ["brand_code", "product_line", "name"]
