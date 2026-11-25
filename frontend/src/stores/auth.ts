import { create } from 'zustand'
import {
  api,
  ApiError,
  refreshAccessToken,
  refreshFailedOffline,
  setAccessToken,
  setSessionExpiredHandler,
} from '@/lib/api'
import type { Me } from '@/lib/types'
import { db, getMeta, setMeta } from '@/offline/db'

type Status = 'loading' | 'authed' | 'anon'

interface AuthState {
  status: Status
  me: Me | null
  /**
   * True when the app was opened with no connection and is running on the identity remembered from
   * the last sign-in. It can only work with data already on this device (the till); everything
   * else needs the server. It becomes a normal session as soon as the server can be reached.
   */
  offlineSession: boolean
  bootstrap: () => Promise<void>
  /** Called when the connection returns: turns an offline session into a real one. */
  resume: () => Promise<void>
  login: (email: string, password: string, remember?: boolean) => Promise<void>
  logout: () => Promise<void>
  can: (permission: string) => boolean
}

const ME_KEY = 'me'

async function rememberedIdentity(): Promise<Me | undefined> {
  try {
    return await getMeta<Me>(ME_KEY)
  } catch {
    return undefined
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'loading',
  me: null,
  offlineSession: false,

  // Restores a session from the refresh cookie on page load.
  bootstrap: async () => {
    if (!(await refreshAccessToken())) {
      if (refreshFailedOffline()) {
        // No connection, which says nothing about the session. Carry on with the remembered user.
        const me = await rememberedIdentity()
        if (me) return set({ me, status: 'authed', offlineSession: true })
      }
      return set({ status: 'anon', me: null, offlineSession: false })
    }
    try {
      const me = await api<Me>('/auth/me')
      await setMeta(ME_KEY, me)
      set({ me, status: 'authed', offlineSession: false })
    } catch (e) {
      if (e instanceof ApiError && e.network) {
        const me = await rememberedIdentity()
        if (me) return set({ me, status: 'authed', offlineSession: true })
      }
      set({ status: 'anon', me: null, offlineSession: false })
    }
  },

  resume: async () => {
    if (!get().offlineSession) return
    if (!(await refreshAccessToken())) {
      // Offline again: stay as we are. Reachable but refused: the session really has ended.
      if (!refreshFailedOffline()) set({ status: 'anon', me: null, offlineSession: false })
      return
    }
    try {
      const me = await api<Me>('/auth/me')
      await setMeta(ME_KEY, me)
      set({ me, offlineSession: false })
    } catch {
      /* still unreachable: remain offline */
    }
  },

  login: async (email, password, remember = false) => {
    const { access_token } = await api<{ access_token: string }>('/auth/login', 'POST', {
      email,
      password,
      remember,
    })
    setAccessToken(access_token)
    const me = await api<Me>('/auth/me')
    await setMeta(ME_KEY, me)
    set({ me, status: 'authed', offlineSession: false })
  },

  logout: async () => {
    await api('/auth/logout', 'POST').catch(() => undefined)
    setAccessToken(null)
    // Forget who was signed in. Sales not yet synced stay on the device and are sent after the
    // next sign-in; they are never lost by signing out.
    await db.meta.delete(ME_KEY)
    set({ me: null, status: 'anon', offlineSession: false })
  },

  can: (permission) => get().me?.permissions.includes(permission) ?? false,
}))

setSessionExpiredHandler(() =>
  useAuthStore.setState({ me: null, status: 'anon', offlineSession: false }),
)
