import { apiClient } from './client'
import type { Brand, UploadConfig } from '../types'

export async function fetchBrands(): Promise<Brand[]> {
  const { data } = await apiClient.get<{ brands: Brand[] }>('/masterdata/brands/')
  return data.brands
}

export async function fetchUploadConfigs(): Promise<UploadConfig[]> {
  const { data } = await apiClient.get<{ upload_configs: UploadConfig[] }>(
    '/masterdata/upload-configs/',
  )
  return data.upload_configs
}
