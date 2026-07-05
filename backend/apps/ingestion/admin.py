from django.contrib import admin, messages

from .loader import rollback_batch
from .models import UploadBatch


@admin.register(UploadBatch)
class UploadBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "brand", "file_name", "status", "row_count", "created_at")
    list_filter = ("brand", "status")
    search_fields = ("file_name", "object_key")
    readonly_fields = [f.name for f in UploadBatch._meta.fields]
    actions = ["rollback_selected_batches"]

    @admin.action(description="Roll back selected batches (delete their fact_sales rows)")
    def rollback_selected_batches(self, request, queryset):
        not_loaded = queryset.exclude(status=UploadBatch.Status.LOADED)
        if not_loaded.exists():
            self.message_user(
                request,
                f"Skipped {not_loaded.count()} batch(es) not in 'loaded' status.",
                level=messages.WARNING,
            )
        total_deleted = 0
        for batch in queryset.filter(status=UploadBatch.Status.LOADED):
            total_deleted += rollback_batch(batch)
        self.message_user(
            request, f"Rolled back {total_deleted} fact_sales row(s) across the selected batches."
        )
