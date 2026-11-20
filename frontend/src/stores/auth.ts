import { create } from 'zustand'
import { api, refreshAccessToken, setAccessToken, setSessionExpiredHandler } from '@/lib/api'
import type { Me } from '@/lib/types'

type Status = 'loading' | 'authed' | 'anon'

interface AuthState {
  status: Status
  me: Me | null
  bootstrap: () => Promise<void>
  login: (email: string, password: string, remember?: boolean) => Promise<void>
  logout: () => Promise<void>
  can: (permission: string) => boolean
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'loading',
  me: null,

  // Restores a session from the refresh cookie on page load.
  bootstrap: async () => {
    if (!(await refreshAccessToken())) return set({ status: 'anon', me: null })
    try {
      set({ me: await api<Me>('/auth/me'), status: 'authed' })
    } catch {
      set({ status: 'anon', me: null })
    }
  },

  login: async (email, password, remember = false) => {
    const { access_token } = await api<{ access_token: string }>('/auth/login', 'POST', {
      email,
      password,
      remember,
    })
    setAccessToken(access_token)
    set({ me: await api<Me>('/auth/me'), status: 'authed' })
  },

  logout: async () => {
    await api('/auth/logout', 'POST').catch(() => undefined)
    setAccessToken(null)
    set({ me: null, status: 'anon' })
  },

  can: (permission) => get().me?.permissions.includes(permission) ?? false,
}))

setSessionExpiredHandler(() => useAuthStore.setState({ me: null, status: 'anon' }))
