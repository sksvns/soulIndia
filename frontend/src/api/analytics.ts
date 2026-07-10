import { apiClient } from './client'
import type {
  CategoryPerfRow,
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

export async function fetchDashboardSummary(
  brandCode: string,
  filters: Filters,
): Promise<DashboardSummary> {
  const { data } = await apiClient.get<DashboardSummary>('/analytics/dashboard/', {
    params: { brand_code: brandCode, ...filters },
  })
  return data
}

export async function fetchStorePerf(
  brandCode: string,
  filters: Filters,
  orderBy: OrderBy,
): Promise<StorePerfRow[]> {
  const { data } = await apiClient.get<{ results: StorePerfRow[] }>('/analytics/stores/', {
    params: { brand_code: brandCode, order_by: orderBy, ...filters },
  })
  return data.results
}

export async function fetchCategoryPerf(
  brandCode: string,
  filters: Filters,
  orderBy: OrderBy,
): Promise<CategoryPerfRow[]> {
  const { data } = await apiClient.get<{ results: CategoryPerfRow[] }>('/analytics/categories/', {
    params: { brand_code: brandCode, order_by: orderBy, ...filters },
  })
  return data.results
}

export async function fetchStoreTrend(
  brandCode: string,
  dimension: TrendDimension,
  metric: TrendMetric,
  store?: string,
): Promise<TrendPoint[]> {
  const { data } = await apiClient.get<{ results: TrendPoint[] }>('/analytics/trends/stores/', {
    params: { brand_code: brandCode, dimension, metric, store: store || undefined },
  })
  return data.results
}

export async function fetchCategoryTrend(
  brandCode: string,
  dimension: TrendDimension,
  metric: TrendMetric,
  category?: string,
  subCategory?: string,
  store?: string,
): Promise<TrendPoint[]> {
  const { data } = await apiClient.get<{ results: TrendPoint[] }>(
    '/analytics/trends/categories/',
    {
      params: {
        brand_code: brandCode,
        dimension,
        metric,
        category: category || undefined,
        sub_category: subCategory || undefined,
        store: store || undefined,
      },
    },
  )
  return data.results
}
