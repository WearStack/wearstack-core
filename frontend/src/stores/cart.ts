import { create } from 'zustand'
import { newId } from '@/lib/money'
import type { LookupVariant } from '@/lib/types'

export interface CartLine {
  variantId: string
  name: string
  label: string
  sku: string
  unitPrice: string
  stock: number | null
  qty: number
  discount: string
}

interface CartState {
  lines: CartLine[]
  customer: { id: string; name: string } | null
  /** One key per distinct basket: a network retry reuses it, so a sale can never double-post. */
  saleKey: string
  add: (v: LookupVariant) => void
  setQty: (variantId: string, qty: number) => void
  setDiscount: (variantId: string, discount: string) => void
  remove: (variantId: string) => void
  setCustomer: (c: { id: string; name: string } | null) => void
  clear: () => void
}

const label = (v: LookupVariant) => [v.size, v.colour].filter(Boolean).join(' / ') || 'Default'

export const useCartStore = create<CartState>((set) => ({
  lines: [],
  customer: null,
  saleKey: newId(),
  // Any change makes it a different sale, so it gets a fresh idempotency key.
  add: (v) =>
    set((s) => {
      const existing = s.lines.find((l) => l.variantId === v.variant_id)
      const lines = existing
        ? s.lines.map((l) => (l === existing ? { ...l, qty: l.qty + 1 } : l))
        : [
            ...s.lines,
            {
              variantId: v.variant_id,
              name: v.product_name,
              label: label(v),
              sku: v.sku,
              unitPrice: v.selling_price,
              stock: v.quantity,
              qty: 1,
              discount: '0',
            },
          ]
      return { lines, saleKey: newId() }
    }),
  setQty: (variantId, qty) =>
    set((s) => ({
      lines: s.lines.map((l) => (l.variantId === variantId ? { ...l, qty: Math.max(1, qty) } : l)),
      saleKey: newId(),
    })),
  setDiscount: (variantId, discount) =>
    set((s) => ({
      lines: s.lines.map((l) => (l.variantId === variantId ? { ...l, discount } : l)),
      saleKey: newId(),
    })),
  remove: (variantId) =>
    set((s) => ({ lines: s.lines.filter((l) => l.variantId !== variantId), saleKey: newId() })),
  setCustomer: (customer) => set({ customer, saleKey: newId() }),
  clear: () => set({ lines: [], customer: null, saleKey: newId() }),
}))
