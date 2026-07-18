import { useEffect, useState } from 'react'
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
import { downloadErrorReport } from '../api/ingestion'
import { useAuth } from '../auth/AuthContext'
import { useOperations } from '../operations/OperationsContext'
import type { UploadConfig, UploadStatus } from '../types'

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
  // uploadBatch/uploading live in OperationsProvider (mounted once in
  // AppLayout, above this page) rather than local state -- so the poll
  // loop that tracks this batch to completion keeps running, and its
  // success/error toast still fires, even if the user navigates to a
  // different page before it finishes.
  const { uploadBatch, uploading, startUpload } = useOperations()
  const [configs, setConfigs] = useState<UploadConfig[]>([])
  const [brandCode, setBrandCode] = useState<string | undefined>(undefined)
  const [productLine, setProductLine] = useState<string | undefined>(undefined)
  const [file, setFile] = useState<File | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    fetchUploadConfigs().then(setConfigs)
  }, [])

  const brandOptions = [...new Map(configs.map((c) => [c.brand_code, c.brand_code])).keys()].map(
    (code) => ({ label: code, value: code }),
  )
  const productLineOptions = configs
    .filter((c) => c.brand_code === brandCode)
    .map((c) => ({ label: c.product_line, value: c.product_line }))

  const handleSubmit = async () => {
    if (!file || !brandCode || !productLine) return
    setSubmitError(null)
    try {
      await startUpload(file, brandCode, productLine)
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : undefined
      setSubmitError(detail || 'Upload failed to start -- check the file and try again.')
    }
  }

  const handleDownloadErrorReport = async () => {
    if (!uploadBatch) return
    const blob = await downloadErrorReport(uploadBatch.batch_id)
    triggerBrowserDownload(blob, `batch_${uploadBatch.batch_id}_errors.csv`)
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
          loading={uploading}
          onClick={handleSubmit}
        >
          Upload
        </Button>

        {submitError && <Alert type="error" title={submitError} showIcon />}

        {uploadBatch && (
          <Card size="small" title={`Batch #${uploadBatch.batch_id}`}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="File">{uploadBatch.file_name}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={STATUS_COLOR[uploadBatch.status]}>{uploadBatch.status}</Tag>
              </Descriptions.Item>
              {uploadBatch.row_count !== null && (
                <Descriptions.Item label="Rows loaded">{uploadBatch.row_count}</Descriptions.Item>
              )}
              {uploadBatch.error_count !== null && uploadBatch.error_count > 0 && (
                <Descriptions.Item label="Rows rejected">
                  {uploadBatch.error_count}
                </Descriptions.Item>
              )}
              {uploadBatch.failure_reason && (
                <Descriptions.Item label="Reason">
                  <Typography.Text type="danger">{uploadBatch.failure_reason}</Typography.Text>
                </Descriptions.Item>
              )}
            </Descriptions>
            {uploadBatch.error_report_key && (
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
