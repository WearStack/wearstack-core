import { create } from 'zustand'

const KEY = 'wearstack.activeStore'
const read = (): string => {
  try {
    return localStorage.getItem(KEY) ?? ''
  } catch {
    return '' // storage can be blocked (private windows); the app works without it
  }
}

interface UiState {
  online: boolean
  setOnline: (online: boolean) => void
  /** The store the user is working in. Operational screens and the Overview follow it. */
  activeStoreId: string
  setActiveStoreId: (id: string) => void
}

export const useUiStore = create<UiState>((set) => ({
  online: navigator.onLine,
  setOnline: (online) => set({ online }),
  activeStoreId: read(),
  setActiveStoreId: (activeStoreId) => {
    try {
      localStorage.setItem(KEY, activeStoreId)
    } catch {
      /* not persisted; still applies for this session */
    }
    set({ activeStoreId })
  },
}))
