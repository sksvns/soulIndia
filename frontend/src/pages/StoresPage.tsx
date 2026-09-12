import { useCallback, useEffect, useRef, useState } from 'react'
import { Table, Select, Card, Alert, Space, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchStorePerf } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import { CacheStatus } from '../components/CacheStatus'
import { StoresFilterBar } from '../components/StoresFilterBar'
import { formatINR, formatNumber } from '../utils/format'
import type { Filters, OrderBy, PageSize, StorePerfRow } from '../types'

const ORDER_BY_OPTIONS: { label: string; value: OrderBy }[] = [
  { label: 'Net Sales', value: 'net' },
  { label: 'MRP Sales', value: 'mrp' },
  { label: 'Quantity', value: 'quantity' },
  { label: 'Discount %', value: 'discount_pct' },
]

const PAGE_SIZE_OPTIONS: { label: string; value: PageSize }[] = [
  { label: '10', value: '10' },
  { label: '20', value: '20' },
  { label: '50', value: '50' },
  { label: '100', value: '100' },
  { label: '200', value: '200' },
  { label: 'All', value: 'all' },
]

// No column-level sorter here, deliberately: sorting is entirely
// server-side over the complete result (the "Order by" control below),
// never a client-side re-sort of whichever page happens to be loaded
// (client feedback).
const columns: ColumnsType<StorePerfRow> = [
  { title: 'Store', dataIndex: 'store_name' },
  { title: 'Code', dataIndex: 'store_code' },
  { title: 'City', dataIndex: 'city' },
  { title: 'Zone', dataIndex: 'zone' },
  { title: 'MRP Sales', dataIndex: 'mrp_value', align: 'right', render: (v: number) => formatINR(v) },
  { title: 'Net Sales', dataIndex: 'net_value', align: 'right', render: (v: number) => formatINR(v) },
  { title: 'Quantity', dataIndex: 'quantity', align: 'right', render: (v: number) => formatNumber(v) },
  {
    title: 'Discount %',
    dataIndex: 'discount_pct',
    align: 'right',
    render: (v: number | null) => (v === null ? '—' : `${v}%`),
  },
]

export function StoresPage() {
  const { brands, brandsLoading } = useFilters()
  const [brand, setBrandState] = useState<string | undefined>(undefined)
  const [filters, setFiltersState] = useState<Filters>({})
  const [orderBy, setOrderByState] = useState<OrderBy>('net')
  const [pageSize, setPageSizeState] = useState<PageSize>('10')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<StorePerfRow[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [cacheHit, setCacheHit] = useState(false)
  const [cachedAt, setCachedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestId = useRef(0)

  const setBrand = (v: string | undefined) => {
    setBrandState(v)
    setPage(1)
  }
  const setFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFiltersState((prev) => {
      const next = { ...prev }
      if (value === undefined || value === '') delete next[key]
      else next[key] = value
      return next
    })
    setPage(1)
  }
  const setOrderBy = (v: OrderBy) => {
    setOrderByState(v)
    setPage(1)
  }
  const setPageSize = (v: PageSize) => {
    setPageSizeState(v)
    setPage(1)
  }
  const clearAll = () => {
    setBrandState(undefined)
    setFiltersState({})
    setPage(1)
  }

  const load = useCallback(
    (refresh: boolean) => {
      const id = ++requestId.current
      const setBusy = refresh ? setRefreshing : setLoading
      setBusy(true)
      setError(null)
      fetchStorePerf(brand, filters, orderBy, page, pageSize, refresh)
        .then((data) => {
          if (id !== requestId.current) return
          setRows(data.results)
          setTotalCount(data.total_count)
          setCacheHit(data.cache_hit)
          setCachedAt(data.cached_at)
        })
        .catch(() => {
          if (id === requestId.current) setError('Could not load store performance for this selection.')
        })
        .finally(() => {
          if (id === requestId.current) setBusy(false)
        })
    },
    [brand, filters, orderBy, page, pageSize],
  )

  useEffect(() => {
    load(false)
  }, [load])

  if (error) {
    return <Alert type="error" title={error} showIcon />
  }

  return (
    <>
      <StoresFilterBar
        brands={brands}
        brandsLoading={brandsLoading}
        brand={brand}
        onBrandChange={setBrand}
        filters={filters}
        onFilterChange={setFilter}
        onClear={clearAll}
      />
      <Card
        title="Stores"
        extra={
          <Space>
            <Typography.Text type="secondary">Order by</Typography.Text>
            <Select
              style={{ width: 150 }}
              value={orderBy}
              onChange={setOrderBy}
              options={ORDER_BY_OPTIONS}
            />
            <Typography.Text type="secondary">Rows per page</Typography.Text>
            <Select
              style={{ width: 90 }}
              value={pageSize}
              onChange={setPageSize}
              options={PAGE_SIZE_OPTIONS}
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
        <Table<StorePerfRow>
          rowKey="store_id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          pagination={
            pageSize === 'all'
              ? false
              : {
                  current: page,
                  pageSize: Number(pageSize),
                  total: totalCount,
                  showSizeChanger: false,
                  onChange: setPage,
                  showTotal: (total) => `${total} stores`,
                }
          }
        />
      </Card>
    </>
  )
}
