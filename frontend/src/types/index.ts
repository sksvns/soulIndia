export interface Brand {
  brand_code: string
  brand_name: string
}

export interface Me {
  email: string
  full_name: string
  is_staff: boolean
  groups: string[]
  permissions: string[]
}

export interface FilterAttribute {
  canonical_name: string
  source: string
  is_dimension: boolean
  data_type: string
}

export interface Totals {
  mrp_value: number
  net_value: number
  discount_value: number
  quantity: number
}

export interface SeasonBreakdown extends Totals {
  season_code: string | null
}

export interface DashboardSummary {
  total: Totals
  by_season: SeasonBreakdown[]
  brand_code: string
  cache_hit: boolean
}

// Global filter bar state -- keys match attribute_registry canonical_name
// and analytics query params exactly (apps/analytics/views.py
// FILTER_PARAM_NAMES), so this object can be spread straight into a
// request's query params with no translation layer.
export interface Filters {
  financial_year?: string
  month?: number
  season?: string
  store?: string
  city?: string
  zone?: string
  category?: string
  sub_category?: string
  gender?: string
  discount_range?: string
}

export type OrderBy = 'net' | 'mrp' | 'quantity' | 'discount_pct'

export interface StorePerfRow {
  store_id: number
  store_code: string
  store_name: string
  city: string | null
  zone: string | null
  mrp_value: number
  net_value: number
  discount_value: number
  quantity: number
  discount_pct: number | null
}

export interface CategoryPerfRow {
  category: string | null
  sub_category: string | null
  mrp_value: number
  net_value: number
  discount_value: number
  quantity: number
  discount_pct: number | null
}

export interface UploadConfig {
  brand_code: string
  product_line: string
  name: string
}

export type UploadStatus =
  | 'received'
  | 'parsing'
  | 'validating'
  | 'failed'
  | 'loaded'
  | 'rolled_back'

export interface UploadBatch {
  batch_id: number
  brand_code: string
  file_name: string
  status: UploadStatus
  row_count: number | null
  error_count: number | null
  slices: unknown[]
  error_report_key: string | null
  failure_reason: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}
