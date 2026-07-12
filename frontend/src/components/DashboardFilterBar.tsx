import { useEffect, useState } from 'react'
import { Select, Space } from 'antd'
import { fetchDashboardFilterOptions } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import type { DashboardFilterOptions } from '../types'

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

// Dashboard's own simplified filter bar (client feedback) -- just
// brand/year/month/category/sub_category/store, all real dropdowns
// populated from what actually has data for the selected brand, instead
// of the full filter bar's free-text fields the other analytics pages
// still use.
export function DashboardFilterBar() {
  const { brands, brandsLoading, brand, setBrand, filters, setFilter } = useFilters()
  const [options, setOptions] = useState<DashboardFilterOptions>(EMPTY_OPTIONS)
  const [optionsLoading, setOptionsLoading] = useState(false)

  useEffect(() => {
    if (!brand) {
      setOptions(EMPTY_OPTIONS)
      return
    }
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

  return (
    <Space wrap size="small" style={{ padding: '12px 16px', width: '100%' }}>
      <Select
        style={{ width: 180 }}
        placeholder="Brand"
        loading={brandsLoading}
        value={brand}
        onChange={setBrand}
        options={brands.map((b) => ({ label: b.brand_name, value: b.brand_code }))}
      />
      <Select
        style={{ width: 120 }}
        placeholder="Year"
        allowClear
        loading={optionsLoading}
        value={filters.financial_year}
        onChange={(v) => setFilter('financial_year', v)}
        options={options.financial_years.map((y) => ({ label: y, value: y }))}
      />
      <Select
        style={{ width: 130 }}
        placeholder="Month"
        allowClear
        value={filters.month}
        onChange={(v) => setFilter('month', v)}
        options={MONTH_OPTIONS}
      />
      <Select
        style={{ width: 160 }}
        placeholder="Category"
        allowClear
        loading={optionsLoading}
        value={filters.category}
        onChange={(v) => setFilter('category', v)}
        options={options.categories.map((c) => ({ label: c, value: c }))}
      />
      <Select
        style={{ width: 160 }}
        placeholder="Sub-category"
        allowClear
        loading={optionsLoading}
        value={filters.sub_category}
        onChange={(v) => setFilter('sub_category', v)}
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
        onChange={(v) => setFilter('store', v)}
        options={options.stores.map((s) => ({ label: s.store_name, value: s.store_code }))}
      />
    </Space>
  )
}
