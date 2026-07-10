import { useEffect, useState } from 'react'
import { Card, Segmented, Select, Input, Empty, Alert, Space, Typography, Spin } from 'antd'
import ReactECharts from 'echarts-for-react'
import { fetchCategoryTrend, fetchStoreTrend } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import { formatINR, formatNumber } from '../utils/format'
import type { TrendDimension, TrendMetric, TrendPoint } from '../types'

type Entity = 'store' | 'category'

const ENTITY_OPTIONS = [
  { label: 'Store', value: 'store' },
  { label: 'Category', value: 'category' },
]
const DIMENSION_OPTIONS = [
  { label: 'YoY', value: 'financial_year' },
  { label: 'MoM', value: 'month' },
  { label: 'Season', value: 'season' },
]
const METRIC_OPTIONS: { label: string; value: TrendMetric }[] = [
  { label: 'Net Sales', value: 'net' },
  { label: 'MRP Sales', value: 'mrp' },
  { label: 'Quantity', value: 'quantity' },
]

function formatMetric(value: number, metric: TrendMetric): string {
  return metric === 'quantity' ? formatNumber(value) : formatINR(value)
}

function trendChartOption(points: TrendPoint[], metric: TrendMetric) {
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => formatMetric(v, metric),
    },
    grid: { left: 80, right: 24, bottom: 32, top: 24 },
    xAxis: { type: 'category', data: points.map((p) => p.label) },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => formatMetric(v, metric) },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        areaStyle: {},
        data: points.map((p) => p.value),
      },
    ],
  }
}

export function TrendsPage() {
  const { brand, filters } = useFilters()
  const [entity, setEntity] = useState<Entity>('store')
  const [dimension, setDimension] = useState<TrendDimension>('financial_year')
  const [metric, setMetric] = useState<TrendMetric>('net')
  const [storeCode, setStoreCode] = useState('')
  const [points, setPoints] = useState<TrendPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!brand) return
    let cancelled = false
    setLoading(true)
    setError(null)
    const request =
      entity === 'store'
        ? fetchStoreTrend(brand, dimension, metric, storeCode)
        : fetchCategoryTrend(
            brand,
            dimension,
            metric,
            filters.category,
            filters.sub_category,
            filters.store,
          )
    request
      .then((data) => {
        if (!cancelled) setPoints(data)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load trend data for this selection.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [
    brand,
    entity,
    dimension,
    metric,
    storeCode,
    filters.category,
    filters.sub_category,
    filters.store,
  ])

  if (!brand) {
    return <Empty description="Select a brand to see its trends" />
  }

  if (error) {
    return <Alert type="error" title={error} showIcon />
  }

  const categoryScopeText = [
    filters.category && `category=${filters.category}`,
    filters.sub_category && `sub_category=${filters.sub_category}`,
    filters.store && `store(s)=${filters.store}`,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <Card
      title="Trends"
      extra={
        <Space wrap>
          <Segmented
            options={ENTITY_OPTIONS}
            value={entity}
            onChange={(v) => setEntity(v as Entity)}
          />
          <Segmented
            options={DIMENSION_OPTIONS}
            value={dimension}
            onChange={(v) => setDimension(v as TrendDimension)}
          />
          <Select
            style={{ width: 140 }}
            value={metric}
            onChange={setMetric}
            options={METRIC_OPTIONS}
          />
          {entity === 'store' && (
            <Input
              style={{ width: 140 }}
              placeholder="Store code (optional)"
              value={storeCode}
              onChange={(e) => setStoreCode(e.target.value)}
              allowClear
            />
          )}
        </Space>
      }
    >
      {entity === 'category' && categoryScopeText && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          Scoped to {categoryScopeText} (via the global filter bar)
        </Typography.Text>
      )}
      {entity === 'store' && !storeCode && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          Showing the whole brand -- enter a store code above to scope to one store.
        </Typography.Text>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <Spin size="large" />
        </div>
      ) : points.length > 0 ? (
        <ReactECharts option={trendChartOption(points, metric)} style={{ height: 400 }} />
      ) : (
        <Empty description="No data for this selection" />
      )}
    </Card>
  )
}
