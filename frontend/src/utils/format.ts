// Indian digit grouping (lakh/crore, e.g. 1,80,58,39,454) everywhere a
// rupee amount or a plain count is shown -- one shared formatter so a
// future change (decimals, symbol) doesn't need finding every call site.
const INR_CURRENCY = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

const INR_NUMBER = new Intl.NumberFormat('en-IN')

export function formatINR(value: number): string {
  return INR_CURRENCY.format(value)
}

export function formatNumber(value: number): string {
  return INR_NUMBER.format(value)
}

// "as of <time>" for a cached analytics response -- coarse buckets rather
// than a live-ticking clock, since it's only ever read right after a
// fetch/refresh, not kept on screen long enough for the bucket to matter.
export function formatRelativeTime(isoString: string): string {
  const then = new Date(isoString).getTime()
  const diffSeconds = Math.round((Date.now() - then) / 1000)
  if (diffSeconds < 5) return 'just now'
  if (diffSeconds < 60) return `${diffSeconds}s ago`
  const diffMinutes = Math.round(diffSeconds / 60)
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.round(diffHours / 24)
  return `${diffDays}d ago`
}
