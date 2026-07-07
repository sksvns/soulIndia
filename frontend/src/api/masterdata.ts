import { apiClient } from './client'
import type { Brand } from '../types'

export async function fetchBrands(): Promise<Brand[]> {
  const { data } = await apiClient.get<{ brands: Brand[] }>('/masterdata/brands/')
  return data.brands
}
