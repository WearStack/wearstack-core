import Dexie, { type EntityTable } from 'dexie'

/** One sellable variant as the till knows it (a copy of the server's catalogue snapshot). */
export interface LocalVariant {
  id: string
  productId: string
  productName: string
  category: string | null
  size: string
  colour: string
  sku: string
  barcode: string
  price: string // tax-inclusive, as a decimal string
  hsnCode: string | null
  quantity: number // the store's stock when the snapshot was taken
  sellable: boolean
}

export interface LocalCustomer {
  id: string
  name: string
  phone: string | null
  stateCode: string | null
}

/**
 * pending   - saved on this device, not yet sent
 * syncing   - being sent right now
 * applied   - the server made it a real sale (final GST invoice issued)
 * conflict  - the server held it for a manager (e.g. the stock was already gone)
 * failed    - the server could not apply it as sent
 * rejected  - a manager voided it
 */
export type QueueStatus = 'pending' | 'syncing' | 'applied' | 'conflict' | 'failed' | 'rejected'

export interface QueuedLine {
  variantId: string
  name: string
  label: string
  sku: string
  quantity: number
  unitPrice: string
  discount: string
}

export interface QueuedPayment {
  method: 'cash' | 'upi' | 'card'
  amount: string
  reference: string | null
}

export interface SyncOutcome {
  operationId: string | null
  saleId: string | null
  invoiceNumber: string | null
  conflicts: Record<string, unknown>[]
  errorCode: string | null
  errorMessage: string | null
}

export interface QueuedSale {
  /** Also the idempotency key sent to the server: sending it twice can never make two sales. */
  localId: string
  storeId: string
  cashierId: string
  cashierName: string
  customerId: string | null
  customerName: string | null
  provisionalNumber: string
  soldAt: string // ISO, when the sale really happened (device clock)
  items: QueuedLine[]
  payments: QueuedPayment[]
  total: string // what the customer was asked to pay
  status: QueueStatus
  attempts: number
  nextAttemptAt: number // epoch ms; do not retry before this
  lastError: string | null
  outcome: SyncOutcome | null
}

interface MetaRow {
  key: string
  value: unknown
}

class OfflineDb extends Dexie {
  variants!: EntityTable<LocalVariant, 'id'>
  customers!: EntityTable<LocalCustomer, 'id'>
  queue!: EntityTable<QueuedSale, 'localId'>
  meta!: EntityTable<MetaRow, 'key'>

  constructor() {
    super('wearstack-offline')
    this.version(1).stores({
      variants: 'id, barcode, sku, productName',
      customers: 'id, name, phone',
      queue: 'localId, status, soldAt, storeId',
      meta: 'key',
    })
  }
}

export const db = new OfflineDb()

export async function getMeta<T>(key: string): Promise<T | undefined> {
  return (await db.meta.get(key))?.value as T | undefined
}

export async function setMeta(key: string, value: unknown): Promise<void> {
  await db.meta.put({ key, value })
}
