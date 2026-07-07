import { Empty } from 'antd'

export function ComingSoonPage({ title }: { title: string }) {
  return <Empty description={`${title} -- coming in a later day of the build plan`} />
}
