from django.urls import path

from . import views

urlpatterns = [
    path("uploads/", views.UploadCreateView.as_view(), name="upload-create"),
    path("uploads/<int:batch_id>/", views.UploadDetailView.as_view(), name="upload-detail"),
]
