import { useEffect, useState } from 'react'
import { Select, Space, Button } from 'antd'
import { ClearOutlined } from '@ant-design/icons'
import { fetchSizeFilterOptions } from '../api/analytics'
import type { Brand, Filters, SizeFilterOptions } from '../types'

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

const EMPTY_OPTIONS: SizeFilterOptions = {
  financial_years: [],
  stores: [],
  categories: [],
  genders: [],
}

interface SizesFilterBarProps {
  brands: Brand[]
  brandsLoading: boolean
  brand: string | undefined
  onBrandChange: (brand: string | undefined) => void
  filters: Filters
  onFilterChange: <K extends keyof Filters>(key: K, value: Filters[K]) => void
  onClear: () => void
}

// The Sizes page's own filter bar -- same conventions as ColorsFilterBar
// (brand/year/month/store + Category, defaulting to every category
// combined).
export function SizesFilterBar({
  brands,
  brandsLoading,
  brand,
  onBrandChange,
  filters,
  onFilterChange,
  onClear,
}: SizesFilterBarProps) {
  const [options, setOptions] = useState<SizeFilterOptions>(EMPTY_OPTIONS)
  const [optionsLoading, setOptionsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setOptionsLoading(true)
    fetchSizeFilterOptions(brand)
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
      <Select
        style={{ width: 160 }}
        placeholder="Category (all)"
        allowClear
        loading={optionsLoading}
        value={filters.category}
        onChange={(v) => onFilterChange('category', v)}
        options={options.categories.map((c) => ({ label: c, value: c }))}
      />
      <Select
        style={{ width: 150 }}
        placeholder="Gender (all)"
        allowClear
        loading={optionsLoading}
        value={filters.gender}
        onChange={(v) => onFilterChange('gender', v)}
        options={options.genders.map((g) => ({ label: g, value: g }))}
      />
      {activeCount > 0 && (
        <Button icon={<ClearOutlined />} onClick={onClear}>
          Clear ({activeCount})
        </Button>
      )}
    </Space>
  )
}
