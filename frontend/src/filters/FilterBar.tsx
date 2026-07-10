import { Select, Input, Button, Space } from 'antd'
import { ClearOutlined } from '@ant-design/icons'
import { useFilters } from './FilterContext'

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
// data -- safe to hardcode, unlike store/city/category which are free-form
// per-brand values with no "list distinct values" endpoint yet.
const DISCOUNT_RANGE_OPTIONS = ['markup', '0-10%', '10-20%', '20-30%', '30-40%', '40-50%', '50%+'].map(
  (label) => ({ label, value: label }),
)

export function FilterBar() {
  const { brands, brandsLoading, brand, setBrand, filters, setFilter, clearFilters } =
    useFilters()
  const activeCount = Object.keys(filters).length

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
      <Input
        style={{ width: 110 }}
        placeholder="FY e.g. 24-25"
        value={filters.financial_year ?? ''}
        onChange={(e) => setFilter('financial_year', e.target.value || undefined)}
        allowClear
      />
      <Select
        style={{ width: 130 }}
        placeholder="Month"
        allowClear
        value={filters.month}
        onChange={(v) => setFilter('month', v)}
        options={MONTH_OPTIONS}
      />
      <Input
        style={{ width: 110 }}
        placeholder="Season"
        value={filters.season ?? ''}
        onChange={(e) => setFilter('season', e.target.value || undefined)}
        allowClear
      />
      <Select
        mode="tags"
        style={{ width: 200 }}
        placeholder="Store code(s)"
        tokenSeparators={[',']}
        value={filters.store ? filters.store.split(',') : []}
        onChange={(vals) => setFilter('store', vals.length ? vals.join(',') : undefined)}
        options={[]}
      />
      <Input
        style={{ width: 120 }}
        placeholder="City"
        value={filters.city ?? ''}
        onChange={(e) => setFilter('city', e.target.value || undefined)}
        allowClear
      />
      <Input
        style={{ width: 100 }}
        placeholder="Zone"
        value={filters.zone ?? ''}
        onChange={(e) => setFilter('zone', e.target.value || undefined)}
        allowClear
      />
      <Input
        style={{ width: 130 }}
        placeholder="Category"
        value={filters.category ?? ''}
        onChange={(e) => setFilter('category', e.target.value || undefined)}
        allowClear
      />
      <Input
        style={{ width: 140 }}
        placeholder="Sub-category"
        value={filters.sub_category ?? ''}
        onChange={(e) => setFilter('sub_category', e.target.value || undefined)}
        allowClear
      />
      <Input
        style={{ width: 110 }}
        placeholder="Gender"
        value={filters.gender ?? ''}
        onChange={(e) => setFilter('gender', e.target.value || undefined)}
        allowClear
      />
      <Select
        style={{ width: 140 }}
        placeholder="Discount range"
        allowClear
        value={filters.discount_range}
        onChange={(v) => setFilter('discount_range', v)}
        options={DISCOUNT_RANGE_OPTIONS}
      />
      {activeCount > 0 && (
        <Button icon={<ClearOutlined />} onClick={clearFilters}>
          Clear ({activeCount})
        </Button>
      )}
    </Space>
  )
}
