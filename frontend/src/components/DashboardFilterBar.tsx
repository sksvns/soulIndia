import { useEffect, useState } from 'react'
import { Select, Space, Button } from 'antd'
import { ClearOutlined } from '@ant-design/icons'
import { fetchDashboardFilterOptions } from '../api/analytics'
import type { Brand, DashboardFilterOptions, Filters } from '../types'

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

const EMPTY_OPTIONS: DashboardFilterOptions = {
  financial_years: [],
  categories: [],
  sub_categories: [],
  stores: [],
}

interface DashboardFilterBarProps {
  brands: Brand[]
  brandsLoading: boolean
  brand: string | undefined
  onBrandChange: (brand: string | undefined) => void
  filters: Filters
  onFilterChange: <K extends keyof Filters>(key: K, value: Filters[K]) => void
  onClear: () => void
}

// Dashboard's own simplified filter bar (client feedback) -- just
// brand/year/month/category/sub_category/store, all real dropdowns
// populated from what actually has data for the current selection,
// instead of the full filter bar's free-text fields the other analytics
// pages still use. Fully controlled (brand/filters/onChange all come
// from the parent) so it's a plain, predictable dropdown: opening it
// never changes anything, only explicitly picking a new value does --
// same as the original shared filter bar.
export function DashboardFilterBar({
  brands,
  brandsLoading,
  brand,
  onBrandChange,
  filters,
  onFilterChange,
  onClear,
}: DashboardFilterBarProps) {
  const [options, setOptions] = useState<DashboardFilterOptions>(EMPTY_OPTIONS)
  const [optionsLoading, setOptionsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setOptionsLoading(true)
    fetchDashboardFilterOptions(brand)
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
        style={{ width: 160 }}
        placeholder="Category"
        allowClear
        loading={optionsLoading}
        value={filters.category}
        onChange={(v) => onFilterChange('category', v)}
        options={options.categories.map((c) => ({ label: c, value: c }))}
      />
      <Select
        style={{ width: 160 }}
        placeholder="Sub-category"
        allowClear
        loading={optionsLoading}
        value={filters.sub_category}
        onChange={(v) => onFilterChange('sub_category', v)}
        options={options.sub_categories.map((c) => ({ label: c, value: c }))}
      />
      <Select
        style={{ width: 220 }}
        placeholder="Store"
        allowClear
        showSearch
        optionFilterProp="label"
        loading={optionsLoading}
        value={filters.store}
        onChange={(v) => onFilterChange('store', v)}
        options={options.stores.map((name) => ({ label: name, value: name }))}
      />
      {activeCount > 0 && (
        <Button icon={<ClearOutlined />} onClick={onClear}>
          Clear ({activeCount})
        </Button>
      )}
    </Space>
  )
}
