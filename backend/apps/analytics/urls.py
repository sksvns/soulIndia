from django.urls import path

from . import views

urlpatterns = [
    path("filters/", views.FilterOptionsView.as_view(), name="analytics-filters"),
    path("dashboard/", views.DashboardSummaryView.as_view(), name="analytics-dashboard"),
    path(
        "dashboard/filter-options/",
        views.DashboardFilterOptionsView.as_view(),
        name="analytics-dashboard-filter-options",
    ),
    path("stores/", views.StorePerfView.as_view(), name="analytics-stores"),
    path(
        "stores/filter-options/",
        views.StoreFilterOptionsView.as_view(),
        name="analytics-stores-filter-options",
    ),
    path("categories/", views.CategoryPerfView.as_view(), name="analytics-categories"),
    path("trends/stores/", views.StoreTrendView.as_view(), name="analytics-trends-stores"),
    path(
        "trends/categories/", views.CategoryTrendView.as_view(), name="analytics-trends-categories"
    ),
]
