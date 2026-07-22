import { apiClient } from './client'
import type { DeletePreview, DeleteResult, MonthWithData, UploadBatch } from '../types'

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

export interface DeleteTarget {
  brandCode: string
  productLine: string
  financialYear: string
  months: number[]
}

export interface MonthsWithDataTarget {
  brandCode: string
  productLine: string
  financialYear: string
}

export async function fetchMonthsWithData(
  target: MonthsWithDataTarget,
): Promise<MonthWithData[]> {
  const { data } = await apiClient.get<{ months: MonthWithData[] }>('/ingestion/delete-months/', {
    params: {
      brand_code: target.brandCode,
      product_line: target.productLine,
      financial_year: target.financialYear,
    },
  })
  return data.months
}

export async function fetchDeletePreview(target: DeleteTarget): Promise<DeletePreview> {
  const { data } = await apiClient.get<DeletePreview>('/ingestion/delete-preview/', {
    params: {
      brand_code: target.brandCode,
      product_line: target.productLine,
      financial_year: target.financialYear,
      months: target.months.join(','),
    },
  })
  return data
}

export async function deleteData(target: DeleteTarget): Promise<DeleteResult> {
  const { data } = await apiClient.post<DeleteResult>('/ingestion/delete/', {
    brand_code: target.brandCode,
    product_line: target.productLine,
    financial_year: target.financialYear,
    months: target.months.join(','),
  })
  return data
}
