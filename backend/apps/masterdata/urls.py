from django.urls import path

from . import views

urlpatterns = [
    path("brands/", views.BrandListView.as_view(), name="brand-list"),
    path("upload-configs/", views.UploadConfigListView.as_view(), name="upload-config-list"),
]
