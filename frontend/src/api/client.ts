import axios, { type InternalAxiosRequestConfig } from 'axios'

const ACCESS_KEY = 'access_token'
const REFRESH_KEY = 'refresh_token'

export const tokenStore = {
  getAccess: () => localStorage.getItem(ACCESS_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  set: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear: () => {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export const apiClient = axios.create({ baseURL: '/api' })

apiClient.interceptors.request.use((config) => {
  const token = tokenStore.getAccess()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Single in-flight refresh shared by every 401'd request that arrives while
// a refresh is already underway, so a burst of concurrent requests doesn't
// fire the refresh endpoint once per request.
let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStore.getRefresh()
  if (!refresh) throw new Error('no refresh token')
  const { data } = await axios.post('/api/auth/refresh/', { refresh })
  tokenStore.set(data.access, refresh)
  return data.access
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config as RetriableConfig | undefined
    if (error.response?.status !== 401 || !config || config._retried) {
      throw error
    }
    config._retried = true
    try {
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null
      })
      const access = await refreshPromise
      config.headers.Authorization = `Bearer ${access}`
      return apiClient(config)
    } catch {
      tokenStore.clear()
      window.location.assign('/login')
      throw error
    }
  },
)
