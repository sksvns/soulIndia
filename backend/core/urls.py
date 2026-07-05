from django.contrib import admin
from django.urls import include, path

from core.health import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/auth/", include("apps.accounts.urls")),
]
