import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, Select, Space, Typography, Spin, Empty, Alert } from 'antd'
import ReactECharts from 'echarts-for-react'
import { fetchColorLineChart, fetchColorRanking } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import { CacheStatus } from '../components/CacheStatus'
import { ColorsFilterBar } from '../components/ColorsFilterBar'
import { formatINR, formatNumber } from '../utils/format'
import type { ColorChartResponse, ColorChartRow, ColorRankingRow, Filters, OrderBy } from '../types'

const METRIC_OPTIONS: { label: string; value: OrderBy }[] = [
  { label: 'Net Sales', value: 'net' },
  { label: 'MRP Sales', value: 'mrp' },
  { label: 'Quantity', value: 'quantity' },
  { label: 'Discount %', value: 'discount_pct' },
]

const METRIC_FIELD: Record<OrderBy, keyof ColorChartRow> = {
  net: 'net_value',
  mrp: 'mrp_value',
  quantity: 'quantity',
  discount_pct: 'discount_pct',
}

const GRANULARITY_TITLE = { year: 'year', month: 'month', week: 'week' } as const

const TOP_DEFAULT_COUNT = 5

function chartOption(chart: ColorChartResponse, metric: OrderBy) {
  const field = METRIC_FIELD[metric]
  const labels = chart.series[0]?.breakdown.map((row) => row.label) ?? []
  const formatValue = (v: number | null) =>
    v === null
      ? '—'
      : metric === 'discount_pct'
        ? `${v}%`
        : metric === 'quantity'
          ? formatNumber(v)
          : formatINR(v)
  return {
    tooltip: { trigger: 'axis', valueFormatter: formatValue },
    legend: { data: chart.series.map((s) => s.color), top: 0 },
    grid: { left: 90, right: 24, bottom: 32, top: 48 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', axisLabel: { formatter: formatValue } },
    series: chart.series.map((s) => ({
      name: s.color,
      type: 'line',
      data: s.breakdown.map((row) => row[field]),
    })),
  }
}

export function ColorsPage() {
  const { brands, brandsLoading } = useFilters()
  const [brand, setBrand] = useState<string | undefined>(undefined)
  const [filters, setFilters] = useState<Filters>({})
  const [metric, setMetric] = useState<OrderBy>('net')

  const [ranking, setRanking] = useState<ColorRankingRow[]>([])
  const [rankingLoading, setRankingLoading] = useState(false)
  const [selectedColors, setSelectedColors] = useState<string[]>([])

  const [chart, setChart] = useState<ColorChartResponse | null>(null)
  const [chartLoading, setChartLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const rankingRequestId = useRef(0)
  const chartRequestId = useRef(0)

  const setFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((prev) => {
      const next = { ...prev }
      if (value === undefined || value === '') delete next[key]
      else next[key] = value
      return next
    })
  }

  const clearAll = () => {
    setBrand(undefined)
    setFilters({})
  }

  // Re-fetches whenever brand/filters (including the Category narrow-
  // down) change, resetting the selection to the new top-5-by-net --
  // same reasoning as CategoriesPage's ranking effect.
  useEffect(() => {
    const id = ++rankingRequestId.current
    setRankingLoading(true)
    fetchColorRanking(brand, filters, 'net')
      .then((data) => {
        if (id !== rankingRequestId.current) return
        setRanking(data.results)
        setSelectedColors(data.results.slice(0, TOP_DEFAULT_COUNT).map((r) => r.color))
      })
      .catch(() => {
        if (id === rankingRequestId.current) setError('Could not load colors for this selection.')
      })
      .finally(() => {
        if (id === rankingRequestId.current) setRankingLoading(false)
      })
  }, [brand, filters])

  const loadChart = useCallback(
    (refresh: boolean) => {
      if (selectedColors.length === 0) {
        setChart(null)
        return
      }
      const id = ++chartRequestId.current
      const setBusy = refresh ? setRefreshing : setChartLoading
      setBusy(true)
      setError(null)
      fetchColorLineChart(brand, filters, selectedColors, refresh)
        .then((data) => {
          if (id !== chartRequestId.current) return
          setChart(data)
        })
        .catch(() => {
          if (id === chartRequestId.current) setError('Could not load the chart for this selection.')
        })
        .finally(() => {
          if (id === chartRequestId.current) setBusy(false)
        })
    },
    [brand, filters, selectedColors],
  )

  useEffect(() => {
    loadChart(false)
  }, [loadChart])

  if (error) {
    return <Alert type="error" title={error} showIcon />
  }

  return (
    <>
      <ColorsFilterBar
        brands={brands}
        brandsLoading={brandsLoading}
        brand={brand}
        onBrandChange={setBrand}
        filters={filters}
        onFilterChange={setFilter}
        onClear={clearAll}
      />
      <Card
        title={chart ? `Sales by ${GRANULARITY_TITLE[chart.granularity]}` : 'Sales by year'}
        extra={
          <Space wrap>
            <Typography.Text type="secondary">Colors</Typography.Text>
            <Select
              mode="multiple"
              style={{ minWidth: 260 }}
              placeholder="Select colors"
              loading={rankingLoading}
              value={selectedColors}
              onChange={setSelectedColors}
              optionFilterProp="label"
              options={ranking.map((r) => ({ label: r.color, value: r.color }))}
            />
            <Typography.Text type="secondary">Metric</Typography.Text>
            <Select
              style={{ width: 150 }}
              value={metric}
              onChange={setMetric}
              options={METRIC_OPTIONS}
            />
            {chart && (
              <CacheStatus
                cacheHit={chart.cache_hit}
                cachedAt={chart.cached_at}
                refreshing={refreshing}
                onRefresh={() => loadChart(true)}
              />
            )}
          </Space>
        }
      >
        <Spin spinning={chartLoading}>
          {selectedColors.length === 0 ? (
            <Empty description="Select at least one color to chart" />
          ) : chart && chart.series.length > 0 ? (
            <ReactECharts option={chartOption(chart, metric)} notMerge style={{ height: 420 }} />
          ) : (
            <Empty description="No data for this filter selection" />
          )}
        </Spin>
      </Card>
    </>
  )
}
