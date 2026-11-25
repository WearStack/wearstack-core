import { api } from '@/lib/api'
import { newId } from '@/lib/money'
import { db, getMeta, setMeta } from './db'

interface StoredDevice {
  id: string
  storeId: string
}

/** A random id for this browser, created once. It never changes unless site data is cleared. */
export async function deviceIdentifier(): Promise<string> {
  let id = await getMeta<string>('deviceIdentifier')
  if (!id) {
    id = newId()
    await setMeta('deviceIdentifier', id)
  }
  return id
}

export async function forgetDevice() {
  await db.meta.delete('device')
}

/** The server's id for this device in this store (registers it on first use). Needs a connection. */
export async function ensureDevice(storeId: string): Promise<string> {
  const known = await getMeta<StoredDevice>('device')
  if (known && known.storeId === storeId) return known.id
  const device = await api<{ id: string }>('/devices', 'POST', {
    identifier: await deviceIdentifier(),
    name: `Till (${typeof navigator === 'undefined' ? 'browser' : navigator.platform || 'browser'})`,
    store_id: storeId,
  })
  await setMeta('device', { id: device.id, storeId })
  return device.id
}
