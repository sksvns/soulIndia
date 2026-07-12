import { useCallback, useEffect, useRef, useState } from 'react'
import { Row, Col, Card, Statistic, Spin, Empty, Alert } from 'antd'
import ReactECharts from 'echarts-for-react'
import { fetchDashboardSummary } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import { CacheStatus } from '../components/CacheStatus'
import { DashboardFilterBar } from '../components/DashboardFilterBar'
import { formatINR, formatNumber } from '../utils/format'
import type { DashboardSummary } from '../types'

function yearChartOption(summary: DashboardSummary) {
  const years = summary.by_year.map((y) => y.financial_year ?? 'Unknown')
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => formatINR(v) },
    legend: { data: ['MRP Sales', 'Net Sales', 'Discount'], top: 0 },
    grid: { left: 90, right: 24, bottom: 32, top: 48 },
    xAxis: { type: 'category', data: years },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => formatINR(v) } },
    series: [
      {
        name: 'MRP Sales',
        type: 'bar',
        data: summary.by_year.map((y) => y.mrp_value),
      },
      {
        name: 'Net Sales',
        type: 'bar',
        data: summary.by_year.map((y) => y.net_value),
      },
      {
        name: 'Discount',
        type: 'bar',
        data: summary.by_year.map((y) => y.discount_value),
      },
    ],
  }
}

export function DashboardPage() {
  const { brand, filters } = useFilters()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
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
      fetchDashboardSummary(brand, filters, refresh)
        .then((data) => {
          if (id === requestId.current) setSummary(data)
        })
        .catch(() => {
          if (id === requestId.current) {
            setError('Could not load the dashboard for this brand/filter selection.')
          }
        })
        .finally(() => {
          if (id === requestId.current) setBusy(false)
        })
    },
    [brand, filters],
  )

  useEffect(() => {
    load(false)
  }, [load])

  return (
    <>
      <DashboardFilterBar />

      {!brand ? (
        <Empty description="Select a brand to see its dashboard" />
      ) : error ? (
        <Alert type="error" title={error} showIcon />
      ) : (
        <Spin spinning={loading}>
          {summary && (
            <>
              <Row gutter={16}>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="Quantity Sold"
                      value={summary.total.quantity}
                      formatter={(v) => formatNumber(Number(v))}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="MRP Sales"
                      value={summary.total.mrp_value}
                      formatter={(v) => formatINR(Number(v))}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="Net Sales"
                      value={summary.total.net_value}
                      formatter={(v) => formatINR(Number(v))}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="Total Discount"
                      value={summary.total.discount_value}
                      formatter={(v) => formatINR(Number(v))}
                    />
                  </Card>
                </Col>
              </Row>

              <Card
                title="Sales by year"
                style={{ marginTop: 16 }}
                extra={
                  <CacheStatus
                    cacheHit={summary.cache_hit}
                    cachedAt={summary.cached_at}
                    refreshing={refreshing}
                    onRefresh={() => load(true)}
                  />
                }
              >
                {summary.by_year.length > 0 ? (
                  <ReactECharts option={yearChartOption(summary)} style={{ height: 400 }} />
                ) : (
                  <Empty description="No data for this filter selection" />
                )}
              </Card>
            </>
          )}
        </Spin>
      )}
    </>
  )
}
