import { create } from 'zustand'
import type { QueuedSale } from '@/offline/db'

/**
 * The receipt of the sale just saved on this device. It lives here, not inside a screen, because
 * the till can switch between its online and offline modes in the middle of a checkout (the
 * connection drops, the request fails): the receipt must still be on screen afterwards.
 */
interface PosState {
  receipt: QueuedSale | null
  /** Why the sale was saved on the device when the cashier expected it to be booked online. */
  droppedMidCheckout: boolean
  show: (sale: QueuedSale, droppedMidCheckout: boolean) => void
  dismiss: () => void
}

export const usePosStore = create<PosState>((set) => ({
  receipt: null,
  droppedMidCheckout: false,
  show: (receipt, droppedMidCheckout) => set({ receipt, droppedMidCheckout }),
  dismiss: () => set({ receipt: null, droppedMidCheckout: false }),
}))
