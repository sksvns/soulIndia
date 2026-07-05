from rest_framework import serializers

from .models import UploadBatch


class UploadBatchSerializer(serializers.ModelSerializer):
    brand_code = serializers.CharField(source="brand.brand_code", read_only=True)

    class Meta:
        model = UploadBatch
        fields = [
            "batch_id",
            "brand_code",
            "file_name",
            "status",
            "row_count",
            "error_count",
            "slices",
            "error_report_key",
            "started_at",
            "finished_at",
            "created_at",
        ]
        read_only_fields = fields
