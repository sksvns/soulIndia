import { useEffect, useState } from 'react'
import { Select, Space, Button } from 'antd'
import { ClearOutlined } from '@ant-design/icons'
import { fetchStoreFilterOptions } from '../api/analytics'
import type { Brand, Filters, StoreFilterOptions } from '../types'

const MONTH_OPTIONS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
].map((name, i) => ({ label: name, value: i + 1 }))

// Fixed system-defined buckets (apps/analytics/migrations
// /0001_create_materialized_views.py DISCOUNT_BUCKET_CASE), not client
// data -- safe to hardcode, same as the original shared filter bar.
const DISCOUNT_RANGE_OPTIONS = ['markup', '0-10%', '10-20%', '20-30%', '30-40%', '40-50%', '50%+'].map(
  (label) => ({ label, value: label }),
)

const EMPTY_OPTIONS: StoreFilterOptions = { financial_years: [] }

interface StoresFilterBarProps {
  brands: Brand[]
  brandsLoading: boolean
  brand: string | undefined
  onBrandChange: (brand: string | undefined) => void
  filters: Filters
  onFilterChange: <K extends keyof Filters>(key: K, value: Filters[K]) => void
  onClear: () => void
}

// The Stores page's own simplified filter bar (client feedback) -- just
// brand/year/month/discount range, all real dropdowns, brand optional
// (defaults to every active brand combined). Fully controlled, same as
// DashboardFilterBar: opening a dropdown never changes anything, only
// explicitly picking a new value does.
export function StoresFilterBar({
  brands,
  brandsLoading,
  brand,
  onBrandChange,
  filters,
  onFilterChange,
  onClear,
}: StoresFilterBarProps) {
  const [options, setOptions] = useState<StoreFilterOptions>(EMPTY_OPTIONS)
  const [optionsLoading, setOptionsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setOptionsLoading(true)
    fetchStoreFilterOptions(brand)
      .then((data) => {
        if (!cancelled) setOptions(data)
      })
      .finally(() => {
        if (!cancelled) setOptionsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [brand])

  const activeCount = (brand ? 1 : 0) + Object.keys(filters).length

  return (
    <Space wrap size="small" style={{ padding: '12px 16px', width: '100%' }}>
      <Select
        style={{ width: 180 }}
        placeholder="Brand (all brands)"
        allowClear
        loading={brandsLoading}
        value={brand}
        onChange={onBrandChange}
        options={brands.map((b) => ({ label: b.brand_name, value: b.brand_code }))}
      />
      <Select
        style={{ width: 120 }}
        placeholder="Year"
        allowClear
        loading={optionsLoading}
        value={filters.financial_year}
        onChange={(v) => onFilterChange('financial_year', v)}
        options={options.financial_years.map((y) => ({ label: y, value: y }))}
      />
      <Select
        style={{ width: 130 }}
        placeholder="Month"
        allowClear
        value={filters.month}
        onChange={(v) => onFilterChange('month', v)}
        options={MONTH_OPTIONS}
      />
      <Select
        style={{ width: 140 }}
        placeholder="Discount range"
        allowClear
        value={filters.discount_range}
        onChange={(v) => onFilterChange('discount_range', v)}
        options={DISCOUNT_RANGE_OPTIONS}
      />
      {activeCount > 0 && (
        <Button icon={<ClearOutlined />} onClick={onClear}>
          Clear ({activeCount})
        </Button>
      )}
    </Space>
  )
}
