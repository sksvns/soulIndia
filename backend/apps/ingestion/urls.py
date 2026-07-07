from django.urls import path

from . import views

urlpatterns = [
    path("uploads/", views.UploadCreateView.as_view(), name="upload-create"),
    path("uploads/<int:batch_id>/", views.UploadDetailView.as_view(), name="upload-detail"),
    path(
        "uploads/<int:batch_id>/error-report/",
        views.ErrorReportDownloadView.as_view(),
        name="upload-error-report",
    ),
    path("backfill/", views.BackfillUploadView.as_view(), name="backfill-create"),
]
