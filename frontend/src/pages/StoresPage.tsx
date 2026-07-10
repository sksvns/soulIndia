import { useEffect, useState } from 'react'
import { Table, Select, Card, Empty, Alert, Space, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchStorePerf } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import type { OrderBy, StorePerfRow } from '../types'

const ORDER_BY_OPTIONS: { label: string; value: OrderBy }[] = [
  { label: 'Net Sales', value: 'net' },
  { label: 'MRP Sales', value: 'mrp' },
  { label: 'Quantity', value: 'quantity' },
  { label: 'Discount %', value: 'discount_pct' },
]

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

const columns: ColumnsType<StorePerfRow> = [
  { title: 'Store', dataIndex: 'store_name', sorter: (a, b) => a.store_name.localeCompare(b.store_name) },
  { title: 'Code', dataIndex: 'store_code', sorter: (a, b) => a.store_code.localeCompare(b.store_code) },
  { title: 'City', dataIndex: 'city' },
  { title: 'Zone', dataIndex: 'zone' },
  {
    title: 'MRP Sales',
    dataIndex: 'mrp_value',
    align: 'right',
    sorter: (a, b) => a.mrp_value - b.mrp_value,
    render: (v: number) => INR.format(v),
  },
  {
    title: 'Net Sales',
    dataIndex: 'net_value',
    align: 'right',
    sorter: (a, b) => a.net_value - b.net_value,
    render: (v: number) => INR.format(v),
  },
  {
    title: 'Quantity',
    dataIndex: 'quantity',
    align: 'right',
    sorter: (a, b) => a.quantity - b.quantity,
  },
  {
    title: 'Discount %',
    dataIndex: 'discount_pct',
    align: 'right',
    sorter: (a, b) => (a.discount_pct ?? 0) - (b.discount_pct ?? 0),
    render: (v: number | null) => (v === null ? '—' : `${v}%`),
  },
]

export function StoresPage() {
  const { brand, filters } = useFilters()
  const [orderBy, setOrderBy] = useState<OrderBy>('net')
  const [rows, setRows] = useState<StorePerfRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!brand) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchStorePerf(brand, filters, orderBy)
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load store performance for this selection.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [brand, filters, orderBy])

  if (!brand) {
    return <Empty description="Select a brand to see its store-wise performance" />
  }

  if (error) {
    return <Alert type="error" message={error} showIcon />
  }

  return (
    <Card
      title="Top 10 stores"
      extra={
        <Space>
          <Typography.Text type="secondary">Order by</Typography.Text>
          <Select
            style={{ width: 150 }}
            value={orderBy}
            onChange={setOrderBy}
            options={ORDER_BY_OPTIONS}
          />
        </Space>
      }
    >
      <Table<StorePerfRow>
        rowKey="store_id"
        columns={columns}
        dataSource={rows}
        loading={loading}
        pagination={false}
      />
    </Card>
  )
}
