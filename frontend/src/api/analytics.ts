import { apiClient } from './client'
import type {
  AnalyticsResponse,
  CategoryPerfRow,
  DashboardFilterOptions,
  DashboardSummary,
  FilterAttribute,
  Filters,
  OrderBy,
  StorePerfRow,
  TrendDimension,
  TrendMetric,
  TrendPoint,
} from '../types'

export async function fetchFilterOptions(): Promise<FilterAttribute[]> {
  const { data } = await apiClient.get<{ filters: FilterAttribute[] }>('/analytics/filters/')
  return data.filters
}

export async function fetchDashboardFilterOptions(
  brandCode: string,
): Promise<DashboardFilterOptions> {
  const { data } = await apiClient.get<DashboardFilterOptions>(
    '/analytics/dashboard/filter-options/',
    { params: { brand_code: brandCode } },
  )
  return data
}

export async function fetchDashboardSummary(
  brandCode: string,
  filters: Filters,
  refresh = false,
): Promise<DashboardSummary> {
  const { data } = await apiClient.get<DashboardSummary>('/analytics/dashboard/', {
    params: { brand_code: brandCode, ...filters, refresh: refresh || undefined },
  })
  return data
}

export async function fetchStorePerf(
  brandCode: string,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<AnalyticsResponse<StorePerfRow[]>> {
  const { data } = await apiClient.get<AnalyticsResponse<StorePerfRow[]>>('/analytics/stores/', {
    params: { brand_code: brandCode, order_by: orderBy, ...filters, refresh: refresh || undefined },
  })
  return data
}

export async function fetchCategoryPerf(
  brandCode: string,
  filters: Filters,
  orderBy: OrderBy,
  refresh = false,
): Promise<AnalyticsResponse<CategoryPerfRow[]>> {
  const { data } = await apiClient.get<AnalyticsResponse<CategoryPerfRow[]>>(
    '/analytics/categories/',
    {
      params: {
        brand_code: brandCode,
        order_by: orderBy,
        ...filters,
        refresh: refresh || undefined,
      },
    },
  )
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
