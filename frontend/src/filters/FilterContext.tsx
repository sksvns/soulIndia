import { createContext, use, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchBrands } from '../api/masterdata'
import type { Brand, Filters } from '../types'

interface FilterContextValue {
  brands: Brand[]
  brandsLoading: boolean
  brand: string | undefined
  setBrand: (brand: string) => void
  filters: Filters
  setFilter: <K extends keyof Filters>(key: K, value: Filters[K]) => void
  clearFilters: () => void
}

const FilterContext = createContext<FilterContextValue | null>(null)

export function FilterProvider({ children }: { children: ReactNode }) {
  const [brands, setBrands] = useState<Brand[]>([])
  const [brandsLoading, setBrandsLoading] = useState(true)
  const [brand, setBrand] = useState<string | undefined>(undefined)
  const [filters, setFilters] = useState<Filters>({})

  useEffect(() => {
    fetchBrands()
      .then((list) => {
        setBrands(list)
        setBrand((current) => current ?? list[0]?.brand_code)
      })
      .finally(() => setBrandsLoading(false))
  }, [])

  const setFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setFilters((prev) => {
      const next = { ...prev }
      if (value === undefined || value === '') {
        delete next[key]
      } else {
        next[key] = value
      }
      return next
    })
  }

  const clearFilters = () => setFilters({})

  const value = useMemo(
    () => ({ brands, brandsLoading, brand, setBrand, filters, setFilter, clearFilters }),
    [brands, brandsLoading, brand, filters],
  )

  return <FilterContext value={value}>{children}</FilterContext>
}

export function useFilters(): FilterContextValue {
  const ctx = use(FilterContext)
  if (!ctx) throw new Error('useFilters must be used within FilterProvider')
  return ctx
}
