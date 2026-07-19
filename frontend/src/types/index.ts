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

export type DashboardGranularity = 'year' | 'month' | 'week'

export interface DashboardBreakdownRow extends Totals {
  label: string
}

export interface DashboardSummary {
  total: Totals
  breakdown: DashboardBreakdownRow[]
  granularity: DashboardGranularity
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Distinct values actually present in a brand's data, for the Dashboard's
// own simplified filter bar (brand/year/month/category/sub_category/store).
// stores is store *names*, not codes -- deduped across brands so the same
// physical store (a different store_code per brand) appears once, not
// once per brand (client feedback).
export interface DashboardFilterOptions {
  financial_years: string[]
  categories: string[]
  sub_categories: string[]
  stores: string[]
}

// Shape shared by every analytics list endpoint (stores/categories/
// trends) -- cache_hit/cached_at ride alongside the actual results so the
// UI can show "as of <time>" and a manual refresh control consistently.
export interface AnalyticsResponse<T> {
  results: T
  brand_code: string
  cache_hit: boolean
  cached_at: string
}

export type PageSize = '10' | '20' | '50' | '100' | '200' | 'all'

// Stores: paged + sorted server-side over the complete result (client
// feedback), brand_code optional like the Dashboard's -- omitted means
// every active brand combined.
export interface PaginatedAnalyticsResponse<T> {
  results: T
  total_count: number
  page: number
  page_size: PageSize
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Distinct financial years actually present, for the Stores page's own
// simplified filter bar's Year dropdown.
export interface StoreFilterOptions {
  financial_years: string[]
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

export type TrendDimension = 'financial_year' | 'month' | 'season'
export type TrendMetric = 'net' | 'mrp' | 'quantity'

export interface TrendPoint {
  label: string
  value: number
}

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

// Every category (client feedback: never capped at a top-N, grouped by
// top-level category only -- sub_category isn't a dimension the
// Categories page exposes anymore). Feeds both the ranking display and
// the line chart's multi-select (top 5 by net becomes the default).
export interface CategoryRankingRow extends Totals {
  category: string
  discount_pct: number | null
}

export interface CategoryRankingResponse {
  results: CategoryRankingRow[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Distinct financial years/store names actually present, for the
// Categories page's own filter bar (brand/year/month/store -- client
// feedback, same convention as the Dashboard's).
export interface CategoryFilterOptions {
  financial_years: string[]
  stores: string[]
}

export interface CategoryChartRow extends Totals {
  label: string
  discount_pct: number | null
}

export interface CategorySeries {
  category: string
  breakdown: CategoryChartRow[]
}

// One line per selected category, granularity-adaptive x-axis (same
// year/month/week logic as the Dashboard) shared across every line --
// zero-filled per category so multi-line charts stay aligned point for
// point (see queries.category_line_chart).
export interface CategoryChartResponse {
  granularity: DashboardGranularity
  series: CategorySeries[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Subcategory: identical shape and conventions to Category, one level
// finer -- exactly the same brand/year/month/store filter set, no extra
// Category filter (client feedback).
export interface SubcategoryRankingRow extends Totals {
  sub_category: string
  discount_pct: number | null
}

export interface SubcategoryRankingResponse {
  results: SubcategoryRankingRow[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

export interface SubcategoryFilterOptions {
  financial_years: string[]
  stores: string[]
}

export interface SubcategoryChartRow extends Totals {
  label: string
  discount_pct: number | null
}

export interface SubcategorySeries {
  sub_category: string
  breakdown: SubcategoryChartRow[]
}

export interface SubcategoryChartResponse {
  granularity: DashboardGranularity
  series: SubcategorySeries[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Color: same shape/conventions as Category, but its filter bar also has
// a Category filter (defaults to every category combined, narrow to one
// -- client feedback, same "all, or narrow to one" pattern as brand).
export interface ColorRankingRow extends Totals {
  color: string
  discount_pct: number | null
}

export interface ColorRankingResponse {
  results: ColorRankingRow[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

export interface ColorFilterOptions {
  financial_years: string[]
  stores: string[]
  categories: string[]
}

export interface ColorChartRow extends Totals {
  label: string
  discount_pct: number | null
}

export interface ColorSeries {
  color: string
  breakdown: ColorChartRow[]
}

export interface ColorChartResponse {
  granularity: DashboardGranularity
  series: ColorSeries[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Size: same shape/conventions as Color.
export interface SizeRankingRow extends Totals {
  size: string
  discount_pct: number | null
}

export interface SizeRankingResponse {
  results: SizeRankingRow[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

export interface SizeFilterOptions {
  financial_years: string[]
  stores: string[]
  categories: string[]
}

export interface SizeChartRow extends Totals {
  label: string
  discount_pct: number | null
}

export interface SizeSeries {
  size: string
  breakdown: SizeChartRow[]
}

export interface SizeChartResponse {
  granularity: DashboardGranularity
  series: SizeSeries[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

// Fit: same shape/conventions as Color/Size. Kraus never contributes any
// rows here (no FIT column in its real export) -- same as it already
// doesn't for Subcategory, not an error case the UI needs to handle
// specially.
export interface FitRankingRow extends Totals {
  fit: string
  discount_pct: number | null
}

export interface FitRankingResponse {
  results: FitRankingRow[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
}

export interface FitFilterOptions {
  financial_years: string[]
  stores: string[]
  categories: string[]
}

export interface FitChartRow extends Totals {
  label: string
  discount_pct: number | null
}

export interface FitSeries {
  fit: string
  breakdown: FitChartRow[]
}

export interface FitChartResponse {
  granularity: DashboardGranularity
  series: FitSeries[]
  brand_code: string | null
  cache_hit: boolean
  cached_at: string
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

// Delete Data page: brand + product_line + financial_year + month is the
// full selection (no store filter -- deletes across every store for that
// brand/product_line/period). Preview always reflects exactly what a
// delete would remove (backend shares one query for both).
export interface DeletePreview {
  row_count: number
  store_count: number
  total_net_value: number | null
  min_date: string | null
  max_date: string | null
}

export interface DeleteResult {
  deleted_count: number
}
