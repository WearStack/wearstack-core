import 'fake-indexeddb/auto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/lib/api')>()
  return { ...real, api: vi.fn() }
})

import { api, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { catalogHealth, getCatalogMeta, refreshCatalog, searchVariants } from './catalog'
import { reportReachable, useConnection } from './connection'
import { db, type LocalVariant } from './db'
import { enqueueSale, availableQuantity, pruneSettled, type EnqueueInput } from './queue'
import { backoffMs, BACKOFF_MAX_MS, drainQueue } from './syncEngine'

const apiMock = vi.mocked(api)

const STORE = 's-1'
const V1 = 'v-1'
let seq = 0

const variant = (over: Partial<LocalVariant> = {}): LocalVariant => ({
  id: V1,
  productId: 'p-1',
  productName: 'Classic Shirt',
  category: 'Shirts',
  size: 'M',
  colour: 'Blue',
  sku: 'CLA-M-BLU',
  barcode: '2123456789012',
  price: '1299.00',
  hsnCode: '6205',
  quantity: 10,
  sellable: true,
  ...over,
})

const sale = (over: Partial<EnqueueInput> = {}): EnqueueInput => ({
  operationId: `op-${++seq}`,
  storeId: STORE,
  cashierId: 'u-1',
  cashierName: 'Asha',
  customerId: null,
  customerName: null,
  soldAt: new Date(Date.now() - 60_000),
  items: [
    {
      variantId: V1,
      name: 'Classic Shirt',
      label: 'M / Blue',
      sku: 'CLA-M-BLU',
      quantity: 1,
      unitPrice: '1299.00',
      discount: '0',
    },
  ],
  payments: [{ method: 'cash', amount: '1299.00', reference: null }],
  total: '1299.00',
  ...over,
})

const result = (id: string, status: string, extra: Record<string, unknown> = {}) => ({
  operation_id: `server-${id}`,
  client_operation_id: id,
  status,
  sale_id: status === 'applied' ? `sale-${id}` : null,
  invoice_number: status === 'applied' ? 'MAIN/26-27/00001' : null,
  conflicts: [],
  error_code: null,
  error_message: null,
  ...extra,
})

const catalogSnapshot = (quantity = 10) => ({
  store_id: STORE,
  store_name: 'Main Store',
  generated_at: new Date().toISOString(),
  settings: {
    free_discount_percent: 10,
    offline_warn_hours: 24,
    offline_block_hours: 72,
    offline_max_sale_age_days: 7,
    sync_batch_max: 50,
  },
  variants: [
    {
      id: V1,
      product_id: 'p-1',
      product_name: 'Classic Shirt',
      category: 'Shirts',
      size: 'M',
      colour: 'Blue',
      sku: 'CLA-M-BLU',
      barcode: '2123456789012',
      price: '1299.00',
      hsn_code: '6205',
      quantity,
      sellable: true,
    },
  ],
  customers: [{ id: 'c-1', name: 'Asha Rao', phone: '9876543210', state_code: '29' }],
})

/** A pretend server: routes by path so each test only describes what differs. */
function server(
  handlers: {
    sales?: (body: { operations: { client_operation_id: string }[] }) => unknown
    [k: string]: unknown
  } = {},
) {
  apiMock.mockImplementation(async (path: string, _method?: string, body?: unknown) => {
    if (path === '/devices') return { id: 'device-1' }
    if (path.startsWith('/sync/catalog')) return catalogSnapshot(5)
    if (path === '/sync/sales') {
      if (handlers.sales) return handlers.sales(body as never)
      const ops = (body as { operations: { client_operation_id: string }[] }).operations
      return { results: ops.map((o) => result(o.client_operation_id, 'applied')) }
    }
    if (path.startsWith('/sync/operations/') && handlers.operation)
      return (handlers.operation as (p: string) => unknown)(path)
    throw new ApiError(404, `unexpected ${path}`)
  })
}

beforeEach(async () => {
  vi.clearAllMocks()
  await Promise.all([db.variants.clear(), db.customers.clear(), db.queue.clear(), db.meta.clear()])
  useConnection.setState({ online: true })
  useAuthStore.setState({ status: 'authed' })
  await db.variants.put(variant())
})

describe('queue', () => {
  it('stores a sale once, however many times it is enqueued', async () => {
    const input = sale()
    const a = await enqueueSale(input)
    const b = await enqueueSale(input) // e.g. the checkout was retried
    expect(b.localId).toBe(a.localId)
    expect(b.provisionalNumber).toBe(a.provisionalNumber)
    expect(await db.queue.count()).toBe(1)
  })

  it('numbers provisional receipts per device, in order, in a recognisable format', async () => {
    const nums = []
    for (let i = 0; i < 3; i++) nums.push((await enqueueSale(sale())).provisionalNumber)
    expect(nums[0]).toMatch(/^OFF-[A-Z0-9]{4}-0001$/)
    const code = nums[0].split('-')[1]
    expect(nums).toEqual([`OFF-${code}-0001`, `OFF-${code}-0002`, `OFF-${code}-0003`])
  })

  it('counts held and unsent sales against the stock, but not settled ones', async () => {
    expect(await availableQuantity(V1)).toBe(10)
    const a = await enqueueSale(sale())
    await enqueueSale(sale({ items: [{ ...sale().items[0], quantity: 3 }] }))
    expect(await availableQuantity(V1)).toBe(6) // 10 - 1 - 3
    await db.queue.update(a.localId, { status: 'conflict' })
    expect(await availableQuantity(V1)).toBe(6) // a held sale still left the shelf
    await db.queue.update(a.localId, { status: 'applied' })
    expect(await availableQuantity(V1)).toBe(7) // booked on the server: the next snapshot reflects it
    expect(await availableQuantity('unknown')).toBe(0)
  })

  it('forgets old settled sales but never unsettled ones', async () => {
    const old = new Date(Date.now() - 10 * 86_400_000)
    const done = await enqueueSale(sale({ soldAt: old }))
    const held = await enqueueSale(sale({ soldAt: old }))
    const fresh = await enqueueSale(sale())
    await db.queue.update(done.localId, { status: 'applied' })
    await db.queue.update(held.localId, { status: 'conflict' })
    await db.queue.update(fresh.localId, { status: 'applied' })
    await pruneSettled()
    expect((await db.queue.toArray()).map((s) => s.localId).sort()).toEqual(
      [held.localId, fresh.localId].sort(),
    )
  })
})

describe('catalogue cache', () => {
  it('replaces the local copy with the server snapshot', async () => {
    await db.variants.put(variant({ id: 'stale', sku: 'OLD' }))
    server()
    const meta = await refreshCatalog(STORE, 'device-1')
    expect((await db.variants.toArray()).map((v) => v.id)).toEqual([V1]) // the stale row is gone
    expect((await db.variants.get(V1))?.quantity).toBe(5)
    expect(await db.customers.count()).toBe(1)
    expect(meta.settings).toMatchObject({ freeDiscountPercent: 10, blockHours: 72, batchMax: 50 })
    expect((await getCatalogMeta())?.storeName).toBe('Main Store')
  })

  it('finds a variant by exact barcode, exact SKU, or part of the name', async () => {
    await db.variants.bulkPut([
      variant({ id: 'a', barcode: '2000000000017', sku: 'SHI-M-BLU', productName: 'Linen Shirt' }),
      variant({ id: 'b', barcode: '2000000000024', sku: 'DEN-32-BLK', productName: 'Slim Denim' }),
    ])
    expect((await searchVariants('2000000000024')).map((v) => v.id)).toEqual(['b'])
    expect((await searchVariants('shi-m-blu')).map((v) => v.id)).toEqual(['a']) // SKU, any case
    expect((await searchVariants('denim')).map((v) => v.id)).toEqual(['b'])
    expect((await searchVariants('  ')).length).toBe(0)
    expect((await searchVariants('nothing like this')).length).toBe(0)
  })

  it('judges how far the catalogue can be trusted offline', () => {
    const meta = {
      storeId: STORE,
      storeName: 'Main',
      fetchedAt: 0,
      settings: {
        freeDiscountPercent: 10,
        warnHours: 24,
        blockHours: 72,
        maxSaleAgeDays: 7,
        batchMax: 50,
      },
    }
    const hours = (h: number) => h * 3_600_000
    expect(catalogHealth(undefined, STORE)).toBe('missing')
    expect(catalogHealth(meta, 'another-store')).toBe('missing')
    expect(catalogHealth(meta, STORE, hours(1))).toBe('fresh')
    expect(catalogHealth(meta, STORE, hours(24))).toBe('stale')
    expect(catalogHealth(meta, STORE, hours(71.9))).toBe('stale')
    expect(catalogHealth(meta, STORE, hours(72))).toBe('expired') // too old to sell from
  })
})

describe('sync engine', () => {
  it('sends the sale as made, keeps the server answer, and stops once it is booked', async () => {
    server()
    const a = await enqueueSale(
      sale({ payments: [{ method: 'upi', amount: '1299.00', reference: 'U123' }] }),
    )
    const summary = await drainQueue()
    expect(summary).toMatchObject({ sent: 1, applied: 1, held: 0, deferred: false })
    const row = await db.queue.get(a.localId)
    expect(row?.status).toBe('applied')
    expect(row?.outcome).toMatchObject({
      invoiceNumber: 'MAIN/26-27/00001',
      saleId: `sale-${a.localId}`,
    })
    const sent = apiMock.mock.calls.find((c) => c[0] === '/sync/sales')![2] as {
      device_id: string
      operations: Record<string, unknown>[]
    }
    expect(sent.device_id).toBe('device-1')
    expect(sent.operations[0]).toMatchObject({
      client_operation_id: a.localId,
      store_id: STORE,
      cashier_id: 'u-1',
      provisional_number: a.provisionalNumber,
      items: [{ variant_id: V1, quantity: 1, unit_price: '1299.00', discount: '0' }],
      payments: [{ method: 'upi', amount: '1299.00', reference: 'U123' }],
    })
    expect(sent.operations[0].sold_at).toBe(a.soldAt)
    expect((await db.variants.get(V1))?.quantity).toBe(5) // took a fresh snapshot afterwards
    await drainQueue()
    expect(apiMock.mock.calls.filter((c) => c[0] === '/sync/sales').length).toBe(1) // nothing left to send
  })

  it('does not send a cash reference', async () => {
    server()
    await enqueueSale(
      sale({ payments: [{ method: 'cash', amount: '1299.00', reference: 'ignored' }] }),
    )
    await drainQueue()
    const sent = apiMock.mock.calls.find((c) => c[0] === '/sync/sales')![2] as {
      operations: { payments: { reference: unknown }[] }[]
    }
    expect(sent.operations[0].payments[0].reference).toBeNull()
  })

  it('sends the oldest sale first', async () => {
    server()
    const newer = await enqueueSale(sale({ soldAt: new Date(Date.now() - 1_000) }))
    const older = await enqueueSale(sale({ soldAt: new Date(Date.now() - 90_000) }))
    await drainQueue()
    const ops = (
      apiMock.mock.calls.find((c) => c[0] === '/sync/sales')![2] as {
        operations: { client_operation_id: string }[]
      }
    ).operations
    expect(ops.map((o) => o.client_operation_id)).toEqual([older.localId, newer.localId])
  })

  it('keeps a held sale, then learns when a manager accepts it', async () => {
    server({
      sales: (b) => ({
        results: b.operations.map((o) =>
          result(o.client_operation_id, 'conflict', {
            conflicts: [{ code: 'insufficient_stock', requested: 3, available: 1 }],
          }),
        ),
      }),
    })
    const a = await enqueueSale(sale())
    const first = await drainQueue()
    expect(first).toMatchObject({ applied: 0, held: 1 })
    let row = await db.queue.get(a.localId)
    expect(row?.status).toBe('conflict')
    expect(row?.outcome?.conflicts[0]).toMatchObject({ code: 'insufficient_stock', requested: 3 })

    // The manager accepts it on the server; the till finds out on its next pass.
    server({ operation: () => ({ ...result(a.localId, 'applied'), id: 'server-' + a.localId }) })
    await drainQueue()
    row = await db.queue.get(a.localId)
    expect(row?.status).toBe('applied')
    expect(row?.outcome?.invoiceNumber).toBe('MAIN/26-27/00001')
  })

  it('learns when a manager rejects a held sale', async () => {
    server({
      sales: (b) => ({
        results: b.operations.map((o) => result(o.client_operation_id, 'conflict')),
      }),
    })
    const a = await enqueueSale(sale())
    await drainQueue()
    server({
      operation: () => ({ ...result(a.localId, 'rejected'), id: 'x', error_message: null }),
    })
    await drainQueue()
    expect((await db.queue.get(a.localId))?.status).toBe('rejected')
  })

  it('keeps everything and backs off when the network fails, then succeeds later', async () => {
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/devices') return { id: 'device-1' }
      throw new ApiError(0, 'You appear to be offline', true)
    })
    const a = await enqueueSale(sale())
    const t0 = Date.now()
    const summary = await drainQueue()
    expect(summary.applied).toBe(0)
    let row = await db.queue.get(a.localId)
    expect(row).toMatchObject({ status: 'pending', attempts: 1 })
    expect(row!.nextAttemptAt).toBeGreaterThanOrEqual(t0 + 4_000)
    expect(row!.lastError).toMatch(/offline/)

    server() // the network is back, but the retry time has not arrived
    await drainQueue()
    expect((await db.queue.get(a.localId))?.status).toBe('pending')
    await db.queue.update(a.localId, { nextAttemptAt: 0 }) // time passes
    await drainQueue()
    row = await db.queue.get(a.localId)
    expect(row?.status).toBe('applied')
  })

  it('backs off exponentially up to a limit', () => {
    expect([1, 2, 3, 4].map(backoffMs)).toEqual([5_000, 10_000, 20_000, 40_000])
    expect(backoffMs(30)).toBe(BACKOFF_MAX_MS)
    expect(backoffMs(0)).toBe(5_000)
  })

  it('sends nothing while offline or signed out', async () => {
    server()
    const a = await enqueueSale(sale())
    useConnection.setState({ online: false })
    expect(await drainQueue()).toMatchObject({ sent: 0, deferred: true })
    useConnection.setState({ online: true })
    useAuthStore.setState({ status: 'anon' })
    expect(await drainQueue()).toMatchObject({ sent: 0, deferred: true })
    expect(apiMock).not.toHaveBeenCalled()
    expect((await db.queue.get(a.localId))?.status).toBe('pending') // still safely on the device
  })

  it('finds the one bad sale in a batch and still books the others', async () => {
    const bad = await enqueueSale(sale({ soldAt: new Date(Date.now() - 50_000) }))
    const good1 = await enqueueSale(sale({ soldAt: new Date(Date.now() - 90_000) }))
    const good2 = await enqueueSale(sale({ soldAt: new Date(Date.now() - 20_000) }))
    server({
      sales: (b) => {
        if (b.operations.length > 1 || b.operations[0].client_operation_id === bad.localId) {
          if (b.operations.some((o) => o.client_operation_id === bad.localId))
            throw new ApiError(422, 'Each variant is invalid')
        }
        return { results: b.operations.map((o) => result(o.client_operation_id, 'applied')) }
      },
    })
    const summary = await drainQueue()
    expect(summary).toMatchObject({ applied: 2, held: 1 })
    expect((await db.queue.get(good1.localId))?.status).toBe('applied')
    expect((await db.queue.get(good2.localId))?.status).toBe('applied')
    const row = await db.queue.get(bad.localId)
    expect(row?.status).toBe('failed')
    expect(row?.lastError).toBe('Each variant is invalid')
  })

  it('registers the device again if the server has forgotten it', async () => {
    let calls = 0
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/devices') return { id: 'device-' + ++calls }
      throw new ApiError(404, 'Unknown device: register it first')
    })
    const a = await enqueueSale(sale())
    await drainQueue()
    expect(await db.meta.get('device')).toBeUndefined() // forgotten, will be re-registered
    expect((await db.queue.get(a.localId))?.status).toBe('pending')
  })

  it('treats "someone else is deciding it" as not finished', async () => {
    server({
      sales: (b) => ({
        results: b.operations.map((o) => result(o.client_operation_id, 'received')),
      }),
    })
    const a = await enqueueSale(sale())
    await drainQueue()
    const row = await db.queue.get(a.localId)
    expect(row?.status).toBe('pending')
    expect(row!.nextAttemptAt).toBeGreaterThan(Date.now())
  })

  it('leaves a sale pending if the server leaves it out of its answer', async () => {
    server({ sales: () => ({ results: [] }) })
    const a = await enqueueSale(sale())
    await drainQueue()
    expect((await db.queue.get(a.localId))?.status).toBe('pending')
  })

  it('resends a sale that was left half-sent by a closed tab, without duplicating it', async () => {
    server()
    const a = await enqueueSale(sale())
    await db.queue.update(a.localId, { status: 'syncing' }) // the tab closed mid-request
    await drainQueue()
    expect((await db.queue.get(a.localId))?.status).toBe('applied')
    const sent = apiMock.mock.calls.filter((c) => c[0] === '/sync/sales')
    expect(sent.length).toBe(1)
    expect(
      (sent[0][2] as { operations: { client_operation_id: string }[] }).operations[0]
        .client_operation_id,
    ).toBe(a.localId)
  })

  it('shares one run between callers that start at the same time', async () => {
    server()
    await enqueueSale(sale())
    await Promise.all([drainQueue(), drainQueue(), drainQueue()])
    expect(apiMock.mock.calls.filter((c) => c[0] === '/sync/sales').length).toBe(1)
  })
})

describe('connection monitor', () => {
  it('flips offline on a failure and back online when the server answers the probe', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    reportReachable(false)
    expect(useConnection.getState().online).toBe(false)
    await vi.advanceTimersByTimeAsync(10_500)
    expect(fetchMock).toHaveBeenCalled()
    expect(useConnection.getState().online).toBe(true)
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('keeps probing while the server stays unreachable', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network'))
    vi.stubGlobal('fetch', fetchMock)
    reportReachable(false)
    await vi.advanceTimersByTimeAsync(10_500)
    await vi.advanceTimersByTimeAsync(10_500)
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(useConnection.getState().online).toBe(false)
    useConnection.setState({ online: true })
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })
})
