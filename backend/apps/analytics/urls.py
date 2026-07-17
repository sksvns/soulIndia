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
    path(
        "categories/filter-options/",
        views.CategoryFilterOptionsView.as_view(),
        name="analytics-categories-filter-options",
    ),
    path(
        "categories/chart/",
        views.CategoryLineChartView.as_view(),
        name="analytics-categories-chart",
    ),
    path("subcategories/", views.SubcategoryPerfView.as_view(), name="analytics-subcategories"),
    path(
        "subcategories/filter-options/",
        views.SubcategoryFilterOptionsView.as_view(),
        name="analytics-subcategories-filter-options",
    ),
    path(
        "subcategories/chart/",
        views.SubcategoryLineChartView.as_view(),
        name="analytics-subcategories-chart",
    ),
    path("colors/", views.ColorPerfView.as_view(), name="analytics-colors"),
    path(
        "colors/filter-options/",
        views.ColorFilterOptionsView.as_view(),
        name="analytics-colors-filter-options",
    ),
    path("colors/chart/", views.ColorLineChartView.as_view(), name="analytics-colors-chart"),
    path("sizes/", views.SizePerfView.as_view(), name="analytics-sizes"),
    path(
        "sizes/filter-options/",
        views.SizeFilterOptionsView.as_view(),
        name="analytics-sizes-filter-options",
    ),
    path("sizes/chart/", views.SizeLineChartView.as_view(), name="analytics-sizes-chart"),
    path("trends/stores/", views.StoreTrendView.as_view(), name="analytics-trends-stores"),
    path(
        "trends/categories/", views.CategoryTrendView.as_view(), name="analytics-trends-categories"
    ),
]
