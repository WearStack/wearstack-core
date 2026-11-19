import { create } from 'zustand'

interface UiState {
  online: boolean
  setOnline: (online: boolean) => void
}

export const useUiStore = create<UiState>((set) => ({
  online: navigator.onLine,
  setOnline: (online) => set({ online }),
}))
