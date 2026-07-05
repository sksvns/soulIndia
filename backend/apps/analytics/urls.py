from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.DashboardSummaryView.as_view(), name="analytics-dashboard"),
    path("stores/", views.StorePerfView.as_view(), name="analytics-stores"),
    path("categories/", views.CategoryPerfView.as_view(), name="analytics-categories"),
]
