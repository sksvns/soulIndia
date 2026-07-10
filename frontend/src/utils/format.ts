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
