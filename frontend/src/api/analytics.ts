import { apiClient } from './client'
import type {
  AnalyticsResponse,
  CategoryChartResponse,
  CategoryFilterOptions,
  CategoryRankingResponse,
  ColorChartResponse,
  ColorFilterOptions,
  ColorRankingResponse,
  DashboardFilterOptions,
  DashboardSummary,
  FilterAttribute,
  Filters,
  FitChartResponse,
  FitFilterOptions,
  FitRankingResponse,
  OrderBy,
  PageSize,
  PaginatedAnalyticsResponse,
  SizeChartResponse,
  SizeFilterOptions,
  SizeRankingResponse,
  StoreFilterOptions,
  StorePerfRow,
  SubcategoryChartResponse,
  SubcategoryFilterOptions,
  SubcategoryRankingResponse,
  TrendDimension,
  TrendMetric,
  TrendPoint,
} from '../types'

export async function fetchFilterOptions(): Promise<FilterAttribute[]> {
  const { data } = await apiClient.get<{ filters: FilterAttribute[] }>('/analytics/filters/')
  return data.filters
}

// brandCode is optional on both dashboard endpoints -- omitted means
// every active brand combined (client feedback: that's the dashboard's
// default view, not a precondition).
export async function fetchDashboardFilterOptions(
  brandCode: string | undefined,
): Promise<DashboardFilterOptions> {
  const { data } = await apiClient.get<DashboardFilterOptions>(
    '/analytics/dashboard/filter-options/',
    { params: { brand_code: brandCode } },
  )
  return data
}

export async function fetchDashboardSummary(
  brandCode: string | undefined,
  filters: Filters,
  refresh = false,
): Promise<DashboardSummary> {
  const { data } = await apiClient.get<DashboardSummary>('/analytics/dashboard/', {
    params: { brand_code: brandCode, ...filters, refresh: refresh || undefined },
  })
  return data
}

// brandCode is optional here too (client feedback) -- omitted means
// every active brand combined, same convention as the Dashboard.
export async function fetchStorePerf(
  brandCode: string | undefined,
  filters: Filters,
  orderBy: OrderBy,
  page: number,
  pageSize: PageSize,
  refresh = false,
): Promise<PaginatedAnalyticsResponse<StorePerfRow[]>> {
  const { data } = await apiClient.get<PaginatedAnalyticsResponse<StorePerfRow[]>>(
    '/analytics/stores/',
    {
      params: {
        brand_code: brandCode,
        order_by: orderBy,
        page,
        page_size: pageSize,
        ...filters,
        refresh: refresh || undefined,
      },
    },
  )
  return data
}

export async function fetchStoreFilterOptions(
  brandCode: string | undefined,
): Promise<StoreFilterOptions> {
  const { data } = await apiClient.get<StoreFilterOptions>('/analytics/stores/filter-options/', {
    params: { brand_code: brandCode },
  })
  return data
}

// brandCode is optional here too (client feedback) -- omitted means
// every active brand combined, same convention as the Dashboard/Stores.
export async function fetchCategoryRanking(
  brandCode: string | undefined,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<CategoryRankingResponse> {
  const { data } = await apiClient.get<CategoryRankingResponse>('/analytics/categories/', {
    params: {
      brand_code: brandCode,
      order_by: orderBy,
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

export async function fetchCategoryFilterOptions(
  brandCode: string | undefined,
): Promise<CategoryFilterOptions> {
  const { data } = await apiClient.get<CategoryFilterOptions>(
    '/analytics/categories/filter-options/',
    { params: { brand_code: brandCode } },
  )
  return data
}

export async function fetchCategoryLineChart(
  brandCode: string | undefined,
  filters: Filters,
  categories: string[],
  refresh = false,
): Promise<CategoryChartResponse> {
  const { data } = await apiClient.get<CategoryChartResponse>('/analytics/categories/chart/', {
    params: {
      brand_code: brandCode,
      categories: categories.join(','),
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

// Subcategory: identical conventions to Category, one level finer.
export async function fetchSubcategoryRanking(
  brandCode: string | undefined,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<SubcategoryRankingResponse> {
  const { data } = await apiClient.get<SubcategoryRankingResponse>('/analytics/subcategories/', {
    params: {
      brand_code: brandCode,
      order_by: orderBy,
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

export async function fetchSubcategoryFilterOptions(
  brandCode: string | undefined,
): Promise<SubcategoryFilterOptions> {
  const { data } = await apiClient.get<SubcategoryFilterOptions>(
    '/analytics/subcategories/filter-options/',
    { params: { brand_code: brandCode } },
  )
  return data
}

export async function fetchSubcategoryLineChart(
  brandCode: string | undefined,
  filters: Filters,
  subCategories: string[],
  refresh = false,
): Promise<SubcategoryChartResponse> {
  const { data } = await apiClient.get<SubcategoryChartResponse>(
    '/analytics/subcategories/chart/',
    {
      params: {
        brand_code: brandCode,
        sub_categories: subCategories.join(','),
        ...filters,
        refresh: refresh || undefined,
      },
    },
  )
  return data
}

// Color: same conventions as Category, plus a Category filter (client
// feedback: defaults to every category combined, narrow to one).
export async function fetchColorRanking(
  brandCode: string | undefined,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<ColorRankingResponse> {
  const { data } = await apiClient.get<ColorRankingResponse>('/analytics/colors/', {
    params: {
      brand_code: brandCode,
      order_by: orderBy,
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

export async function fetchColorFilterOptions(
  brandCode: string | undefined,
): Promise<ColorFilterOptions> {
  const { data } = await apiClient.get<ColorFilterOptions>('/analytics/colors/filter-options/', {
    params: { brand_code: brandCode },
  })
  return data
}

export async function fetchColorLineChart(
  brandCode: string | undefined,
  filters: Filters,
  colors: string[],
  refresh = false,
): Promise<ColorChartResponse> {
  const { data } = await apiClient.get<ColorChartResponse>('/analytics/colors/chart/', {
    params: {
      brand_code: brandCode,
      colors: colors.join(','),
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

// Size: same conventions as Color.
export async function fetchSizeRanking(
  brandCode: string | undefined,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<SizeRankingResponse> {
  const { data } = await apiClient.get<SizeRankingResponse>('/analytics/sizes/', {
    params: {
      brand_code: brandCode,
      order_by: orderBy,
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

export async function fetchSizeFilterOptions(
  brandCode: string | undefined,
): Promise<SizeFilterOptions> {
  const { data } = await apiClient.get<SizeFilterOptions>('/analytics/sizes/filter-options/', {
    params: { brand_code: brandCode },
  })
  return data
}

export async function fetchSizeLineChart(
  brandCode: string | undefined,
  filters: Filters,
  sizes: string[],
  refresh = false,
): Promise<SizeChartResponse> {
  const { data } = await apiClient.get<SizeChartResponse>('/analytics/sizes/chart/', {
    params: {
      brand_code: brandCode,
      sizes: sizes.join(','),
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

// Fit: same conventions as Color/Size.
export async function fetchFitRanking(
  brandCode: string | undefined,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<FitRankingResponse> {
  const { data } = await apiClient.get<FitRankingResponse>('/analytics/fits/', {
    params: {
      brand_code: brandCode,
      order_by: orderBy,
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

export async function fetchFitFilterOptions(
  brandCode: string | undefined,
): Promise<FitFilterOptions> {
  const { data } = await apiClient.get<FitFilterOptions>('/analytics/fits/filter-options/', {
    params: { brand_code: brandCode },
  })
  return data
}

export async function fetchFitLineChart(
  brandCode: string | undefined,
  filters: Filters,
  fits: string[],
  refresh = false,
): Promise<FitChartResponse> {
  const { data } = await apiClient.get<FitChartResponse>('/analytics/fits/chart/', {
    params: {
      brand_code: brandCode,
      fits: fits.join(','),
      ...filters,
      refresh: refresh || undefined,
    },
  })
  return data
}

export async function fetchStoreTrend(
  brandCode: string,
  dimension: TrendDimension,
  metric: TrendMetric,
  store?: string,
  refresh = false,
): Promise<AnalyticsResponse<TrendPoint[]>> {
  const { data } = await apiClient.get<AnalyticsResponse<TrendPoint[]>>(
    '/analytics/trends/stores/',
    {
      params: {
        brand_code: brandCode,
        dimension,
        metric,
        store: store || undefined,
        refresh: refresh || undefined,
      },
    },
  )
  return data
}

export async function fetchCategoryTrend(
  brandCode: string,
  dimension: TrendDimension,
  metric: TrendMetric,
  category?: string,
  subCategory?: string,
  store?: string,
  refresh = false,
): Promise<AnalyticsResponse<TrendPoint[]>> {
  const { data } = await apiClient.get<AnalyticsResponse<TrendPoint[]>>(
    '/analytics/trends/categories/',
    {
      params: {
        brand_code: brandCode,
        dimension,
        metric,
        category: category || undefined,
        sub_category: subCategory || undefined,
        store: store || undefined,
        refresh: refresh || undefined,
      },
    },
  )
  return data
}
