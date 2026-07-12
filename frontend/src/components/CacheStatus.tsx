import { ReloadOutlined } from '@ant-design/icons'
import { Button, Space, Tag, Tooltip } from 'antd'
import { formatRelativeTime } from '../utils/format'

interface CacheStatusProps {
  cacheHit: boolean
  cachedAt: string
  refreshing: boolean
  onRefresh: () => void
}

export function CacheStatus({ cacheHit, cachedAt, refreshing, onRefresh }: CacheStatusProps) {
  return (
    <Space>
      <Tooltip title={new Date(cachedAt).toLocaleString()}>
        <Tag color={cacheHit ? 'green' : undefined}>
          {cacheHit ? 'cached' : 'live'} &middot; as of {formatRelativeTime(cachedAt)}
        </Tag>
      </Tooltip>
      <Tooltip title="Refresh from the database, bypassing the cache">
        <Button size="small" icon={<ReloadOutlined />} loading={refreshing} onClick={onRefresh} />
      </Tooltip>
    </Space>
  )
}
