import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useDeferredValue, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { LookupVariant } from '@/lib/types'
import { useCartStore } from '@/stores/cart'

const lookupUrl = (q: string, storeId: string) =>
  `/variants/lookup?q=${encodeURIComponent(q)}&store_id=${storeId}`

export function ProductSearch({ storeId }: { storeId: string }) {
  const qc = useQueryClient()
  const add = useCartStore((s) => s.add)
  const [q, setQ] = useState('')
  const deferred = useDeferredValue(q.trim())
  const results = useQuery({
    queryKey: ['lookup', storeId, deferred],
    enabled: deferred.length >= 2,
    queryFn: () => api<LookupVariant[]>(lookupUrl(deferred, storeId)),
  })

  // Barcode scanners type the code and press Enter: a single exact hit goes straight to the cart.
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const term = q.trim()
    if (!term) return
    const hits = await qc.fetchQuery({
      queryKey: ['lookup', storeId, term],
      queryFn: () => api<LookupVariant[]>(lookupUrl(term, storeId)),
    })
    if (hits.length === 1 && (hits[0].quantity ?? 0) > 0) {
      add(hits[0])
      setQ('')
    }
  }

  return (
    <div className="rounded-xl border border-ws-line bg-white p-4">
      <h2 className="mb-3 font-semibold text-ws-ink">Product catalogue</h2>
      <form onSubmit={submit}>
        <Input
          autoFocus
          placeholder="Scan barcode or search name / SKU…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </form>
      <ul className="mt-3 divide-y divide-ws-line">
        {deferred.length >= 2 &&
          results.data?.map((v) => {
            const out = (v.quantity ?? 0) <= 0
            return (
              <li key={v.variant_id} className="flex items-center gap-3 py-3">
                <div className="grow">
                  <b className="text-ws-ink">{v.product_name}</b>
                  <div className="text-xs text-ws-muted">
                    {[v.size, v.colour].filter(Boolean).join(' / ') || 'Default'} · {v.sku} ·{' '}
                    {out ? (
                      <span className="text-red-600">out of stock</span>
                    ) : (
                      `${v.quantity} in stock`
                    )}
                  </div>
                  <b className="text-sm text-ws-ink">{formatMoney(v.selling_price)}</b>
                </div>
                <Button
                  size="sm"
                  disabled={out}
                  onClick={() => add(v)}
                  className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
                >
                  Add
                </Button>
              </li>
            )
          })}
        {deferred.length >= 2 && results.data?.length === 0 && (
          <li className="py-4 text-sm text-ws-muted">No matching products.</li>
        )}
      </ul>
      {deferred.length < 2 && (
        <p className="mt-3 text-sm text-ws-muted">Type at least 2 characters, or scan a barcode.</p>
      )}
    </div>
  )
}
