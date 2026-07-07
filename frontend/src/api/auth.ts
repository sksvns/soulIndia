import { apiClient, tokenStore } from './client'
import type { Me } from '../types'

export async function login(email: string, password: string): Promise<void> {
  const { data } = await apiClient.post('/auth/login/', { email, password })
  tokenStore.set(data.access, data.refresh)
}

export async function fetchMe(): Promise<Me> {
  const { data } = await apiClient.get<Me>('/auth/me/')
  return data
}

export async function logout(): Promise<void> {
  const refresh = tokenStore.getRefresh()
  if (refresh) {
    // Must fire while the access token is still attached -- the endpoint
    // requires auth. Best-effort: the user is logged out client-side
    // regardless of whether the blacklist call itself succeeds.
    await apiClient.post('/auth/logout/', { refresh }).catch(() => undefined)
  }
  tokenStore.clear()
}
