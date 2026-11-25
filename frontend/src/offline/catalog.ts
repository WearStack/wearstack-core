import { api } from '@/lib/api'
import { db, getMeta, setMeta, type LocalVariant } from './db'

export interface CatalogSettings {
  freeDiscountPercent: number
  warnHours: number
  blockHours: number
  maxSaleAgeDays: number
  batchMax: number
}

export interface CatalogMeta {
  storeId: string
  storeName: string
  fetchedAt: number // epoch ms on this device
  settings: CatalogSettings
}

interface ServerCatalog {
  store_id: string
  store_name: string
  settings: {
    free_discount_percent: number
    offline_warn_hours: number
    offline_block_hours: number
    offline_max_sale_age_days: number
    sync_batch_max: number
  }
  variants: {
    id: string
    product_id: string
    product_name: string
    category: string | null
    size: string
    colour: string
    sku: string
    barcode: string
    price: string
    hsn_code: string | null
    quantity: number
    sellable: boolean
  }[]
  customers: { id: string; name: string; phone: string | null; state_code: string | null }[]
}

const META_KEY = 'catalog'

/** Replaces the local copy with a fresh snapshot of the store's catalogue, stock and customers. */
export async function refreshCatalog(storeId: string, deviceId?: string): Promise<CatalogMeta> {
  const qs = `store_id=${storeId}${deviceId ? `&device_id=${deviceId}` : ''}`
  const snap = await api<ServerCatalog>(`/sync/catalog?${qs}`)
  const meta: CatalogMeta = {
    storeId: snap.store_id,
    storeName: snap.store_name,
    fetchedAt: Date.now(),
    settings: {
      freeDiscountPercent: snap.settings.free_discount_percent,
      warnHours: snap.settings.offline_warn_hours,
      blockHours: snap.settings.offline_block_hours,
      maxSaleAgeDays: snap.settings.offline_max_sale_age_days,
      batchMax: snap.settings.sync_batch_max,
    },
  }
  await db.transaction('rw', db.variants, db.customers, db.meta, async () => {
    await db.variants.clear()
    await db.customers.clear()
    await db.variants.bulkPut(
      snap.variants.map((v) => ({
        id: v.id,
        productId: v.product_id,
        productName: v.product_name,
        category: v.category,
        size: v.size,
        colour: v.colour,
        sku: v.sku,
        barcode: v.barcode,
        price: v.price,
        hsnCode: v.hsn_code,
        quantity: v.quantity,
        sellable: v.sellable,
      })),
    )
    await db.customers.bulkPut(
      snap.customers.map((c) => ({
        id: c.id,
        name: c.name,
        phone: c.phone,
        stateCode: c.state_code,
      })),
    )
    await setMeta(META_KEY, meta)
  })
  return meta
}

export const getCatalogMeta = () => getMeta<CatalogMeta>(META_KEY)

export type CatalogHealth = 'missing' | 'fresh' | 'stale' | 'expired'

/** How far the local catalogue can be trusted for offline selling (plan decision D2). */
export function catalogHealth(
  meta: CatalogMeta | undefined,
  storeId: string,
  now = Date.now(),
): CatalogHealth {
  if (!meta || meta.storeId !== storeId) return 'missing'
  const hours = (now - meta.fetchedAt) / 3_600_000
  if (hours >= meta.settings.blockHours) return 'expired' // too old to sell from safely
  if (hours >= meta.settings.warnHours) return 'stale' // sell, but warn
  return 'fresh'
}

const norm = (s: string) => s.trim().toLowerCase()

/** An exact barcode or SKU wins; otherwise a name/SKU substring match, as the online till does. */
export async function searchVariants(query: string, limit = 20): Promise<LocalVariant[]> {
  const q = norm(query)
  if (!q) return []
  const byBarcode = await db.variants.where('barcode').equals(query.trim()).toArray()
  if (byBarcode.length) return byBarcode
  const bySku = await db.variants.where('sku').equals(query.trim().toUpperCase()).toArray()
  if (bySku.length) return bySku
  return db.variants
    .filter((v) => v.productName.toLowerCase().includes(q) || v.sku.toLowerCase().includes(q))
    .limit(limit)
    .toArray()
}
