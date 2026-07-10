import { apiClient } from './client'
import type { UploadBatch } from '../types'

export async function uploadFile(
  file: File,
  brandCode: string,
  productLine: string,
): Promise<UploadBatch> {
  const form = new FormData()
  form.append('file', file)
  form.append('brand_code', brandCode)
  form.append('product_line', productLine)
  const { data } = await apiClient.post<UploadBatch>('/ingestion/uploads/', form)
  return data
}

export async function fetchUploadStatus(batchId: number): Promise<UploadBatch> {
  const { data } = await apiClient.get<UploadBatch>(`/ingestion/uploads/${batchId}/`)
  return data
}

// Fetched as a blob (not a plain <a href>) because the endpoint requires
// the JWT bearer header -- a browser navigating there directly wouldn't
// send it.
export async function downloadErrorReport(batchId: number): Promise<Blob> {
  const { data } = await apiClient.get(`/ingestion/uploads/${batchId}/error-report/`, {
    responseType: 'blob',
  })
  return data
}
