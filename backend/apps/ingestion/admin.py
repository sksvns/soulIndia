from django.contrib import admin, messages

from .loader import DataAlterationNotPermitted, rollback_batch
from .models import DataAlterationAudit, UploadBatch


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
        blocked = 0
        for batch in queryset.filter(status=UploadBatch.Status.LOADED):
            try:
                total_deleted += rollback_batch(batch, request.user)
            except DataAlterationNotPermitted as exc:
                blocked += 1
                self.message_user(request, f"Batch #{batch.batch_id}: {exc}", level=messages.ERROR)
        if blocked:
            self.message_user(
                request,
                f"{blocked} batch(es) require Super Admin access to roll back; see errors above.",
                level=messages.ERROR,
            )
        if total_deleted:
            self.message_user(
                request,
                f"Rolled back {total_deleted} fact_sales row(s) across the selected batches.",
            )


@admin.register(DataAlterationAudit)
class DataAlterationAuditAdmin(admin.ModelAdmin):
    list_display = ("audit_id", "created_at", "user", "brand", "action", "allowed", "batch")
    list_filter = ("action", "allowed", "brand")
    search_fields = ("user__email",)
    readonly_fields = [f.name for f in DataAlterationAudit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
