import { apiClient } from './client'
import type { DashboardSummary, FilterAttribute, Filters } from '../types'

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
