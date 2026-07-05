from django.contrib import admin

from .models import UploadBatch


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "brand", "file_name", "status", "row_count", "created_at")
    list_filter = ("brand", "status")
    search_fields = ("file_name", "object_key")
    readonly_fields = [f.name for f in UploadBatch._meta.fields]
