import { useEffect, useRef, useState } from 'react'
import {
  Card,
  Select,
  Button,
  Upload as AntUpload,
  Tag,
  Typography,
  Space,
  Alert,
  Descriptions,
} from 'antd'
import { UploadOutlined, DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import { isAxiosError } from 'axios'
import { fetchUploadConfigs } from '../api/masterdata'
import { downloadErrorReport, fetchUploadStatus, uploadFile } from '../api/ingestion'
import { useAuth } from '../auth/AuthContext'
import type { UploadBatch, UploadConfig, UploadStatus } from '../types'

const TERMINAL_STATUSES: UploadStatus[] = ['loaded', 'failed', 'rolled_back']
const POLL_INTERVAL_MS = 2000

const STATUS_COLOR: Record<UploadStatus, string> = {
  received: 'blue',
  parsing: 'blue',
  validating: 'blue',
  loaded: 'green',
  failed: 'red',
  rolled_back: 'default',
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export function UploadPage() {
  const { hasPermission } = useAuth()
  const [configs, setConfigs] = useState<UploadConfig[]>([])
  const [brandCode, setBrandCode] = useState<string | undefined>(undefined)
  const [productLine, setProductLine] = useState<string | undefined>(undefined)
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [batch, setBatch] = useState<UploadBatch | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetchUploadConfigs().then(setConfigs)
  }, [])

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const brandOptions = [...new Map(configs.map((c) => [c.brand_code, c.brand_code])).keys()].map(
    (code) => ({ label: code, value: code }),
  )
  const productLineOptions = configs
    .filter((c) => c.brand_code === brandCode)
    .map((c) => ({ label: c.product_line, value: c.product_line }))

  const startPolling = (batchId: number) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const latest = await fetchUploadStatus(batchId)
      setBatch(latest)
      if (TERMINAL_STATUSES.includes(latest.status) && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }, POLL_INTERVAL_MS)
  }

  const handleSubmit = async () => {
    if (!file || !brandCode || !productLine) return
    setSubmitting(true)
    setError(null)
    setBatch(null)
    try {
      const created = await uploadFile(file, brandCode, productLine)
      setBatch(created)
      startPolling(created.batch_id)
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : undefined
      setError(detail || 'Upload failed to start -- check the file and try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDownloadErrorReport = async () => {
    if (!batch) return
    const blob = await downloadErrorReport(batch.batch_id)
    triggerBrowserDownload(blob, `batch_${batch.batch_id}_errors.csv`)
  }

  if (!hasPermission('ingestion.add_uploadbatch')) {
    return (
      <Alert
        type="warning"
        showIcon
        title="You don't have permission to upload files."
      />
    )
  }

  return (
    <Card title="Upload a sales file">
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <Space wrap>
          <div data-testid="brand-select">
            <Select
              style={{ width: 200 }}
              placeholder="Brand"
              value={brandCode}
              onChange={(v) => {
                setBrandCode(v)
                setProductLine(undefined)
              }}
              options={brandOptions}
            />
          </div>
          <div data-testid="product-line-select">
            <Select
              style={{ width: 200 }}
              placeholder="Product line"
              value={productLine}
              onChange={setProductLine}
              disabled={!brandCode}
              options={productLineOptions}
            />
          </div>
        </Space>

        <AntUpload.Dragger
          accept=".csv,.xlsx,.xls,.xlsb"
          maxCount={1}
          beforeUpload={() => false}
          onChange={({ fileList }) => setFile((fileList[0]?.originFileObj as File) ?? null)}
          onRemove={() => setFile(null)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p>Click or drag a CSV/XLSX/XLS/XLSB file here</p>
        </AntUpload.Dragger>

        <Button
          type="primary"
          icon={<UploadOutlined />}
          disabled={!file || !brandCode || !productLine}
          loading={submitting}
          onClick={handleSubmit}
        >
          Upload
        </Button>

        {error && <Alert type="error" title={error} showIcon />}

        {batch && (
          <Card size="small" title={`Batch #${batch.batch_id}`}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="File">{batch.file_name}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={STATUS_COLOR[batch.status]}>{batch.status}</Tag>
              </Descriptions.Item>
              {batch.row_count !== null && (
                <Descriptions.Item label="Rows loaded">{batch.row_count}</Descriptions.Item>
              )}
              {batch.error_count !== null && batch.error_count > 0 && (
                <Descriptions.Item label="Rows rejected">{batch.error_count}</Descriptions.Item>
              )}
              {batch.failure_reason && (
                <Descriptions.Item label="Reason">
                  <Typography.Text type="danger">{batch.failure_reason}</Typography.Text>
                </Descriptions.Item>
              )}
            </Descriptions>
            {batch.error_report_key && (
              <Button
                style={{ marginTop: 12 }}
                icon={<DownloadOutlined />}
                onClick={handleDownloadErrorReport}
              >
                Download error report
              </Button>
            )}
          </Card>
        )}
      </Space>
    </Card>
  )
}
