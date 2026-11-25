import { useLiveQuery } from 'dexie-react-hooks'
import { useDeferredValue, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatMoney } from '@/lib/format'
import { searchVariants } from '@/offline/catalog'
import { availableQuantity } from '@/offline/queue'
import { useCartStore } from '@/stores/cart'

/** Product search over the copy of the catalogue on this device (works with no connection). */
export function OfflineSearch({ blocked }: { blocked: boolean }) {
  const add = useCartStore((s) => s.add)
  const lines = useCartStore((s) => s.lines)
  const [q, setQ] = useState('')
  const deferred = useDeferredValue(q.trim())
  // Stock left to sell = this device's snapshot, less everything already sold here and unsent.
  const results = useLiveQuery(
    async () => {
      if (deferred.length < 2) return []
      const found = await searchVariants(deferred)
      return Promise.all(found.map(async (v) => ({ v, available: await availableQuantity(v.id) })))
    },
    [deferred],
    [],
  )

  const addVariant = (r: { v: (typeof results)[number]['v']; available: number }) =>
    add({
      variant_id: r.v.id,
      product_id: r.v.productId,
      product_name: r.v.productName,
      sku: r.v.sku,
      barcode: r.v.barcode,
      size: r.v.size,
      colour: r.v.colour,
      selling_price: r.v.price,
      quantity: r.available,
    })

  // A scanner types the code and presses Enter: a single sellable hit goes straight in the cart.
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const found = await searchVariants(q.trim())
    if (found.length !== 1 || !found[0].sellable || blocked) return
    const available = await availableQuantity(found[0].id)
    if (available - (lines.find((l) => l.variantId === found[0].id)?.qty ?? 0) <= 0) return
    addVariant({ v: found[0], available })
    setQ('')
  }

  return (
    <div className="rounded-xl border border-ws-line bg-white p-4">
      <h2 className="mb-3 font-semibold text-ws-ink">Product catalogue (on this device)</h2>
      <form onSubmit={submit}>
        <Input
          autoFocus
          placeholder="Scan barcode or search name / SKU…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </form>
      <ul className="mt-3 divide-y divide-ws-line">
        {results.map((r) => {
          const inCart = lines.find((l) => l.variantId === r.v.id)?.qty ?? 0
          const left = r.available - inCart
          const why = !r.v.sellable ? 'cannot be billed' : left <= 0 ? 'no stock left' : null
          return (
            <li key={r.v.id} className="flex items-center gap-3 py-3">
              <div className="grow">
                <b className="text-ws-ink">{r.v.productName}</b>
                <div className="text-xs text-ws-muted">
                  {[r.v.size, r.v.colour].filter(Boolean).join(' / ') || 'Default'} · {r.v.sku} ·{' '}
                  {why ? (
                    <span className="text-red-600">{why}</span>
                  ) : (
                    `${left} left on this device`
                  )}
                </div>
                <b className="text-sm text-ws-ink">{formatMoney(r.v.price)}</b>
              </div>
              <Button
                size="sm"
                disabled={!!why || blocked}
                onClick={() => addVariant(r)}
                className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
              >
                Add
              </Button>
            </li>
          )
        })}
        {deferred.length >= 2 && results.length === 0 && (
          <li className="py-4 text-sm text-ws-muted">No matching products.</li>
        )}
      </ul>
      {deferred.length < 2 && (
        <p className="mt-3 text-sm text-ws-muted">Type at least 2 characters, or scan a barcode.</p>
      )}
    </div>
  )
}
