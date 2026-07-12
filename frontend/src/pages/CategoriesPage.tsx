import { useCallback, useEffect, useRef, useState } from 'react'
import { Table, Select, Card, Empty, Alert, Space, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchCategoryPerf } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import { CacheStatus } from '../components/CacheStatus'
import { formatINR, formatNumber } from '../utils/format'
import type { CategoryPerfRow, OrderBy } from '../types'

const ORDER_BY_OPTIONS: { label: string; value: OrderBy }[] = [
  { label: 'Net Sales', value: 'net' },
  { label: 'MRP Sales', value: 'mrp' },
  { label: 'Quantity', value: 'quantity' },
  { label: 'Discount %', value: 'discount_pct' },
]

const columns: ColumnsType<CategoryPerfRow> = [
  {
    title: 'Category',
    dataIndex: 'category',
    sorter: (a, b) => (a.category ?? '').localeCompare(b.category ?? ''),
    render: (v: string | null) => v ?? '—',
  },
  {
    title: 'Sub-category',
    dataIndex: 'sub_category',
    sorter: (a, b) => (a.sub_category ?? '').localeCompare(b.sub_category ?? ''),
    render: (v: string | null) => v ?? '—',
  },
  {
    title: 'MRP Sales',
    dataIndex: 'mrp_value',
    align: 'right',
    sorter: (a, b) => a.mrp_value - b.mrp_value,
    render: (v: number) => formatINR(v),
  },
  {
    title: 'Net Sales',
    dataIndex: 'net_value',
    align: 'right',
    sorter: (a, b) => a.net_value - b.net_value,
    render: (v: number) => formatINR(v),
  },
  {
    title: 'Quantity',
    dataIndex: 'quantity',
    align: 'right',
    sorter: (a, b) => a.quantity - b.quantity,
    render: (v: number) => formatNumber(v),
  },
  {
    title: 'Discount %',
    dataIndex: 'discount_pct',
    align: 'right',
    sorter: (a, b) => (a.discount_pct ?? 0) - (b.discount_pct ?? 0),
    render: (v: number | null) => (v === null ? '—' : `${v}%`),
  },
]

export function CategoriesPage() {
  const { brand, filters } = useFilters()
  const [orderBy, setOrderBy] = useState<OrderBy>('net')
  const [rows, setRows] = useState<CategoryPerfRow[]>([])
  const [cacheHit, setCacheHit] = useState(false)
  const [cachedAt, setCachedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)

  const load = useCallback(
    (refresh: boolean) => {
      if (!brand) return
      const id = ++requestId.current
      const setBusy = refresh ? setRefreshing : setLoading
      setBusy(true)
      setError(null)
      fetchCategoryPerf(brand, filters, orderBy, refresh)
        .then((data) => {
          if (id !== requestId.current) return
          setRows(data.results)
          setCacheHit(data.cache_hit)
          setCachedAt(data.cached_at)
        })
        .catch(() => {
          if (id === requestId.current) {
            setError('Could not load category performance for this selection.')
          }
        })
        .finally(() => {
          if (id === requestId.current) setBusy(false)
        })
    },
    [brand, filters, orderBy],
  )

  useEffect(() => {
    load(false)
  }, [load])

  if (!brand) {
    return <Empty description="Select a brand to see its category-wise performance" />
  }

  if (error) {
    return <Alert type="error" title={error} showIcon />
  }

  return (
    <Card
      title="Top 10 categories"
      extra={
        <Space>
          <Typography.Text type="secondary">Order by</Typography.Text>
          <Select
            style={{ width: 150 }}
            value={orderBy}
            onChange={setOrderBy}
            options={ORDER_BY_OPTIONS}
          />
          {cachedAt && (
            <CacheStatus
              cacheHit={cacheHit}
              cachedAt={cachedAt}
              refreshing={refreshing}
              onRefresh={() => load(true)}
            />
          )}
        </Space>
      }
    >
      {filters.store && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          Scoped to store(s): {filters.store}
        </Typography.Text>
      )}
      <Table<CategoryPerfRow>
        rowKey={(row) => `${row.category}-${row.sub_category}`}
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={false}
      />
    </Card>
  )
}
