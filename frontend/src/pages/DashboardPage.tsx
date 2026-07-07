import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Spin, Empty, Alert, Tag } from 'antd'
import ReactECharts from 'echarts-for-react'
import { fetchDashboardSummary } from '../api/analytics'
import { useFilters } from '../filters/FilterContext'
import type { DashboardSummary } from '../types'

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

function seasonChartOption(summary: DashboardSummary) {
  const seasons = summary.by_season.map((s) => s.season_code ?? 'Unknown')
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['MRP Sales', 'Net Sales', 'Discount'], top: 0 },
    grid: { left: 60, right: 24, bottom: 32, top: 48 },
    xAxis: { type: 'category', data: seasons },
    yAxis: { type: 'value' },
    series: [
      {
        name: 'MRP Sales',
        type: 'bar',
        data: summary.by_season.map((s) => s.mrp_value),
      },
      {
        name: 'Net Sales',
        type: 'bar',
        data: summary.by_season.map((s) => s.net_value),
      },
      {
        name: 'Discount',
        type: 'bar',
        data: summary.by_season.map((s) => s.discount_value),
      },
    ],
  }
}

export function DashboardPage() {
  const { brand, filters } = useFilters()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!brand) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchDashboardSummary(brand, filters)
      .then((data) => {
        if (!cancelled) setSummary(data)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load the dashboard for this brand/filter selection.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [brand, filters])

  if (!brand) {
    return <Empty description="Select a brand to see its dashboard" />
  }

  if (error) {
    return <Alert type="error" message={error} showIcon />
  }

  return (
    <Spin spinning={loading}>
      {summary && (
        <>
          <Row gutter={16}>
            <Col span={6}>
              <Card>
                <Statistic title="Quantity Sold" value={summary.total.quantity} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="MRP Sales"
                  value={summary.total.mrp_value}
                  formatter={(v) => INR.format(Number(v))}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Net Sales"
                  value={summary.total.net_value}
                  formatter={(v) => INR.format(Number(v))}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Total Discount"
                  value={summary.total.discount_value}
                  formatter={(v) => INR.format(Number(v))}
                />
              </Card>
            </Col>
          </Row>

          <Card
            title="Sales by season"
            style={{ marginTop: 16 }}
            extra={summary.cache_hit ? <Tag color="green">cached</Tag> : <Tag>live</Tag>}
          >
            {summary.by_season.length > 0 ? (
              <ReactECharts option={seasonChartOption(summary)} style={{ height: 360 }} />
            ) : (
              <Empty description="No data for this filter selection" />
            )}
          </Card>
        </>
      )}
    </Spin>
  )
}
