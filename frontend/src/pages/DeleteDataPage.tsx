import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Modal, Select, Space } from 'antd'
import { DeleteOutlined, ExclamationCircleFilled } from '@ant-design/icons'
import { isAxiosError } from 'axios'
import { fetchDashboardFilterOptions } from '../api/analytics'
import { fetchDeletePreview } from '../api/ingestion'
import { fetchUploadConfigs } from '../api/masterdata'
import { useAuth } from '../auth/AuthContext'
import { useOperations } from '../operations/OperationsContext'
import { formatINR } from '../utils/format'
import type { DeletePreview, UploadConfig } from '../types'

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

function monthLabel(month: number | undefined): string {
  return MONTH_OPTIONS.find((m) => m.value === month)?.label ?? ''
}

export function DeleteDataPage() {
  const { hasPermission } = useAuth()
  // The delete request itself is dispatched through OperationsProvider
  // (mounted once in AppLayout) rather than called directly here -- so its
  // success/error toast still fires even if the user has already navigated
  // to a different page by the time it resolves.
  const { deleting, startDelete } = useOperations()
  const [configs, setConfigs] = useState<UploadConfig[]>([])
  const [brandCode, setBrandCode] = useState<string | undefined>(undefined)
  const [productLine, setProductLine] = useState<string | undefined>(undefined)
  const [financialYearOptions, setFinancialYearOptions] = useState<string[]>([])
  const [financialYear, setFinancialYear] = useState<string | undefined>(undefined)
  const [month, setMonth] = useState<number | undefined>(undefined)
  const [preview, setPreview] = useState<DeletePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

  useEffect(() => {
    fetchUploadConfigs().then(setConfigs)
  }, [])

  useEffect(() => {
    if (!brandCode) {
      setFinancialYearOptions([])
      return
    }
    fetchDashboardFilterOptions(brandCode).then((opts) =>
      setFinancialYearOptions(opts.financial_years),
    )
  }, [brandCode])

  useEffect(() => {
    setPreview(null)
    setPreviewError(null)
    if (!brandCode || !productLine || !financialYear || !month) return

    let cancelled = false
    setPreviewLoading(true)
    fetchDeletePreview({ brandCode, productLine, financialYear, month })
      .then((data) => {
        if (!cancelled) setPreview(data)
      })
      .catch((err) => {
        if (cancelled) return
        const detail = isAxiosError(err) ? err.response?.data?.detail : undefined
        setPreviewError(detail || 'Could not load a preview for this selection.')
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [brandCode, productLine, financialYear, month])

  const brandOptions = [...new Map(configs.map((c) => [c.brand_code, c.brand_code])).keys()].map(
    (code) => ({ label: code, value: code }),
  )
  const productLineOptions = configs
    .filter((c) => c.brand_code === brandCode)
    .map((c) => ({ label: c.product_line, value: c.product_line }))

  const handleDeleteClick = () => {
    if (!brandCode || !productLine || !financialYear || !month || !preview) return
    const target = { brandCode, productLine, financialYear, month }

    Modal.confirm({
      title: 'Permanently delete this data?',
      icon: <ExclamationCircleFilled style={{ color: '#ff4d4f' }} />,
      okText: 'Delete permanently',
      okButtonProps: { danger: true },
      cancelText: 'Cancel',
      width: 480,
      content: (
        <div>
          <p>
            This will permanently delete <strong>{preview.row_count.toLocaleString()}</strong>{' '}
            sales row(s) for <strong>{brandCode} / {productLine}</strong>, FY{' '}
            <strong>{financialYear}</strong>, <strong>{monthLabel(month)}</strong>, across{' '}
            <strong>{preview.store_count}</strong> store(s)
            {preview.total_net_value !== null && (
              <> (net value {formatINR(preview.total_net_value)})</>
            )}
            .
          </p>
          <p>
            <strong>This cannot be undone.</strong> Are you sure?
          </p>
        </div>
      ),
      onOk: async () => {
        try {
          await startDelete(target)
          setPreview(null)
          setFinancialYear(undefined)
          setMonth(undefined)
        } catch {
          // failure toast already shown by startDelete -- let the dialog
          // close either way rather than getting stuck open on it.
        }
      },
    })
  }

  if (!hasPermission('ingestion.alter_existing_data')) {
    return (
      <Alert
        type="warning"
        showIcon
        title="You don't have permission to delete data. This requires Super Admin access."
      />
    )
  }

  return (
    <Card title="Delete Data">
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <Alert
          type="warning"
          showIcon
          title="This permanently removes sales data from every store for the selected brand, product line, financial year and month. There is no undo."
        />

        <Space wrap>
          <div data-testid="brand-select">
            <Select
              style={{ width: 200 }}
              placeholder="Brand"
              value={brandCode}
              onChange={(v) => {
                setBrandCode(v)
                setProductLine(undefined)
                setFinancialYear(undefined)
                setMonth(undefined)
              }}
              options={brandOptions}
            />
          </div>
          <div data-testid="product-line-select">
            <Select
              style={{ width: 200 }}
              placeholder="Product line"
              value={productLine}
              onChange={(v) => {
                setProductLine(v)
                setFinancialYear(undefined)
                setMonth(undefined)
              }}
              disabled={!brandCode}
              options={productLineOptions}
            />
          </div>
          <div data-testid="financial-year-select">
            <Select
              style={{ width: 160 }}
              placeholder="Financial year"
              value={financialYear}
              onChange={(v) => {
                setFinancialYear(v)
                setMonth(undefined)
              }}
              disabled={!productLine}
              options={financialYearOptions.map((fy) => ({ label: fy, value: fy }))}
            />
          </div>
          <div data-testid="month-select">
            <Select
              style={{ width: 160 }}
              placeholder="Month"
              value={month}
              onChange={setMonth}
              disabled={!financialYear}
              options={MONTH_OPTIONS}
            />
          </div>
        </Space>

        {previewError && <Alert type="error" title={previewError} showIcon />}

        {preview && (
          <Card size="small" title="What this will delete" loading={previewLoading}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Rows">
                {preview.row_count.toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="Stores">{preview.store_count}</Descriptions.Item>
              <Descriptions.Item label="Total net value">
                {preview.total_net_value !== null ? formatINR(preview.total_net_value) : '--'}
              </Descriptions.Item>
              <Descriptions.Item label="Date range">
                {preview.min_date && preview.max_date
                  ? `${preview.min_date} to ${preview.max_date}`
                  : '--'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        <Button
          danger
          type="primary"
          icon={<DeleteOutlined />}
          disabled={!preview || preview.row_count === 0}
          loading={deleting}
          onClick={handleDeleteClick}
        >
          Delete
        </Button>
      </Space>
    </Card>
  )
}
