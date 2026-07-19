import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, Select, Space, Typography, Spin, Empty, Alert } from 'antd'
import ReactECharts from 'echarts-for-react'
import { fetchFitLineChart, fetchFitRanking } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import { CacheStatus } from '../components/CacheStatus'
import { FitsFilterBar } from '../components/FitsFilterBar'
import { formatINR, formatNumber } from '../utils/format'
import type { FitChartResponse, FitChartRow, FitRankingRow, Filters, OrderBy } from '../types'

const METRIC_OPTIONS: { label: string; value: OrderBy }[] = [
  { label: 'Net Sales', value: 'net' },
  { label: 'MRP Sales', value: 'mrp' },
  { label: 'Quantity', value: 'quantity' },
  { label: 'Discount %', value: 'discount_pct' },
]

const METRIC_FIELD: Record<OrderBy, keyof FitChartRow> = {
  net: 'net_value',
  mrp: 'mrp_value',
  quantity: 'quantity',
  discount_pct: 'discount_pct',
}

const GRANULARITY_TITLE = { year: 'year', month: 'month', week: 'week' } as const

const TOP_DEFAULT_COUNT = 5

function chartOption(chart: FitChartResponse, metric: OrderBy) {
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
    legend: { data: chart.series.map((s) => s.fit), top: 0 },
    grid: { left: 90, right: 24, bottom: 32, top: 48 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', axisLabel: { formatter: formatValue } },
    series: chart.series.map((s) => ({
      name: s.fit,
      type: 'line',
      data: s.breakdown.map((row) => row[field]),
    })),
  }
}

export function FitsPage() {
  const { brands, brandsLoading } = useFilters()
  const [brand, setBrand] = useState<string | undefined>(undefined)
  const [filters, setFilters] = useState<Filters>({})
  const [metric, setMetric] = useState<OrderBy>('net')

  const [ranking, setRanking] = useState<FitRankingRow[]>([])
  const [rankingLoading, setRankingLoading] = useState(false)
  const [selectedFits, setSelectedFits] = useState<string[]>([])

  const [chart, setChart] = useState<FitChartResponse | null>(null)
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
  // same reasoning as ColorsPage's ranking effect.
  useEffect(() => {
    const id = ++rankingRequestId.current
    setRankingLoading(true)
    fetchFitRanking(brand, filters, 'net')
      .then((data) => {
        if (id !== rankingRequestId.current) return
        setRanking(data.results)
        setSelectedFits(data.results.slice(0, TOP_DEFAULT_COUNT).map((r) => r.fit))
      })
      .catch(() => {
        if (id === rankingRequestId.current) setError('Could not load fits for this selection.')
      })
      .finally(() => {
        if (id === rankingRequestId.current) setRankingLoading(false)
      })
  }, [brand, filters])

  const loadChart = useCallback(
    (refresh: boolean) => {
      if (selectedFits.length === 0) {
        setChart(null)
        return
      }
      const id = ++chartRequestId.current
      const setBusy = refresh ? setRefreshing : setChartLoading
      setBusy(true)
      setError(null)
      fetchFitLineChart(brand, filters, selectedFits, refresh)
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
    [brand, filters, selectedFits],
  )

  useEffect(() => {
    loadChart(false)
  }, [loadChart])

  if (error) {
    return <Alert type="error" title={error} showIcon />
  }

  return (
    <>
      <FitsFilterBar
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
            <Typography.Text type="secondary">Fits</Typography.Text>
            <Select
              mode="multiple"
              style={{ minWidth: 260 }}
              placeholder="Select fits"
              loading={rankingLoading}
              value={selectedFits}
              onChange={setSelectedFits}
              optionFilterProp="label"
              options={ranking.map((r) => ({ label: r.fit, value: r.fit }))}
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
          {selectedFits.length === 0 ? (
            <Empty description="Select at least one fit to chart" />
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
