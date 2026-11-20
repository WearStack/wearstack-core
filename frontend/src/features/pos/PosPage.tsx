import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, apiBlob } from '@/lib/api'
import { fromPaise, toPaise } from '@/lib/money'
import type { Quote, SaleResult, Store } from '@/lib/types'
import { useCartStore } from '@/stores/cart'
import { Cart } from './Cart'
import { Payments } from './Payments'
import { paymentsReady, type PaymentRow } from './paymentRules'
import { ProductSearch } from './ProductSearch'

interface Done {
  invoice: string
  total: string
  replayed: boolean
  pdfUrl: string | null
}

export function PosPage() {
  const qc = useQueryClient()
  const { lines, customer, saleKey, clear } = useCartStore()
  const stores = useQuery({ queryKey: ['stores'], queryFn: () => api<Store[]>('/stores') })
  const [chosen, setChosen] = useState('')
  const storeId = chosen || stores.data?.find((s) => s.is_active)?.id || ''
  const [payments, setPayments] = useState<PaymentRow[]>([])
  const [done, setDone] = useState<Done | null>(null)

  // Release the invoice's blob URL when it is replaced or the page closes.
  useEffect(() => () => void (done?.pdfUrl && URL.revokeObjectURL(done.pdfUrl)), [done])

  const discountPaise = lines.map((l) => toPaise(l.discount))
  const invalidDiscount = discountPaise.some((d) => d === null)
  const items = lines.map((l, i) => ({
    variant_id: l.variantId,
    quantity: l.qty,
    discount: fromPaise(discountPaise[i] ?? 0),
  }))

  const quote = useQuery({
    queryKey: ['quote', storeId, customer?.id ?? null, items],
    enabled: !!storeId && lines.length > 0 && !invalidDiscount,
    retry: false,
    placeholderData: keepPreviousData,
    queryFn: () =>
      api<Quote>('/sales/quote', 'POST', {
        store_id: storeId,
        customer_id: customer?.id ?? null,
        items,
      }),
  })
  const total = lines.length > 0 ? quote.data?.grand_total : undefined
  const totalPaise = total ? toPaise(total) : null
  const quoteFresh = !quote.isPlaceholderData && !quote.isError && !!total

  const checkout = useMutation({
    mutationFn: () =>
      api<SaleResult>('/sales', 'POST', {
        idempotency_key: saleKey,
        store_id: storeId,
        customer_id: customer?.id ?? null,
        items,
        payments: payments.map((p) => ({
          method: p.method,
          amount: fromPaise(toPaise(p.amount) ?? 0),
          reference: p.method === 'cash' ? null : p.reference.trim(),
        })),
      }),
    onSuccess: async (sale) => {
      let pdfUrl: string | null = null
      try {
        pdfUrl = URL.createObjectURL(await apiBlob(`/sales/${sale.id}/invoice.pdf`))
      } catch {
        /* the sale is complete either way; the invoice can be reopened later */
      }
      setDone({
        invoice: sale.invoice_number,
        total: sale.grand_total,
        replayed: sale.replayed,
        pdfUrl,
      })
      clear()
      setPayments([])
      void qc.invalidateQueries({ queryKey: ['lookup'] })
      void qc.invalidateQueries({ queryKey: ['stock'] })
    },
  })

  const canComplete =
    quoteFresh && totalPaise !== null && paymentsReady(payments, totalPaise) && !checkout.isPending

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ws-ink">Point of Sale</h1>
          <p className="text-sm text-ws-muted">Create a new customer transaction.</p>
        </div>
        {(stores.data?.length ?? 0) > 1 && (
          <select
            className="border-input h-9 rounded-md border bg-white px-2 text-sm"
            value={storeId}
            aria-label="Store"
            onChange={(e) => {
              setChosen(e.target.value)
              clear()
              setPayments([])
            }}
          >
            {stores.data
              ?.filter((s) => s.is_active)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
          </select>
        )}
      </div>

      {done && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-green-200 bg-green-50 p-4"
          role="status"
        >
          <div>
            <b className="text-green-800">Sale complete · {done.invoice}</b>
            <div className="text-sm text-green-800">
              Total ₹{done.total}
              {done.replayed && ' · this sale had already been recorded; no duplicate was created'}
            </div>
          </div>
          <div className="flex gap-2">
            {done.pdfUrl && (
              <a
                href={done.pdfUrl}
                target="_blank"
                rel="noreferrer"
                className="rounded-md bg-ws-blue px-3 py-2 text-sm font-medium text-white"
              >
                Open invoice (PDF)
              </a>
            )}
            <Button variant="outline" size="sm" onClick={() => setDone(null)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {!storeId ? (
        <p className="text-sm text-ws-muted">No active store available to you.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <ProductSearch storeId={storeId} />
          <div className="space-y-4">
            <Cart
              quote={quote.data}
              quoteError={quote.isError ? quote.error.message : null}
              invalidDiscount={invalidDiscount}
            />
            {lines.length > 0 && (
              <>
                <Payments rows={payments} onChange={setPayments} total={total} />
                {checkout.isError && (
                  <p className="text-destructive text-sm">{checkout.error.message}</p>
                )}
                <div className="flex gap-2">
                  <Button
                    className="grow bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
                    disabled={!canComplete}
                    onClick={() => checkout.mutate()}
                  >
                    {checkout.isPending ? 'Completing…' : 'Complete sale'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      clear()
                      setPayments([])
                    }}
                  >
                    Clear
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
