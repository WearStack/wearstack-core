import { fromPaise, toPaise } from '@/lib/money'
import type { Me } from '@/lib/types'
import type { QueuedSale } from '@/offline/db'
import { enqueueSale } from '@/offline/queue'
import { drainQueue } from '@/offline/syncEngine'
import type { CartLine } from '@/stores/cart'
import type { PaymentRow } from './paymentRules'

interface Input {
  saleKey: string
  storeId: string
  me: Me
  customer: { id: string; name: string } | null
  lines: CartLine[]
  payments: PaymentRow[]
  /** The tax-inclusive total shown to the customer, as a decimal string like "1299.00". */
  total: string
}

/** Saves a finished sale on this device and tries to send it. The sale is never lost: it stays
 *  queued, under the till's sale key, until the server has booked it. */
export async function saveSaleLocally(input: Input): Promise<QueuedSale> {
  const sale = await enqueueSale({
    operationId: input.saleKey,
    storeId: input.storeId,
    cashierId: input.me.id,
    cashierName: input.me.full_name,
    customerId: input.customer?.id ?? null,
    customerName: input.customer?.name ?? null,
    soldAt: new Date(),
    items: input.lines.map((l) => ({
      variantId: l.variantId,
      name: l.name,
      label: l.label,
      sku: l.sku,
      quantity: l.qty,
      unitPrice: l.unitPrice,
      discount: fromPaise(toPaise(l.discount) ?? 0),
    })),
    payments: input.payments.map((p) => ({
      method: p.method,
      amount: fromPaise(toPaise(p.amount) ?? 0),
      reference: p.method === 'cash' ? null : p.reference.trim(),
    })),
    total: input.total,
  })
  void drainQueue() // if the connection is actually fine, this goes straight through
  return sale
}
