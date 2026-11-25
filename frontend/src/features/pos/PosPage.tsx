import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, ApiError, apiBlob } from '@/lib/api'
import { fromPaise, toPaise } from '@/lib/money'
import { useActiveStore } from '@/lib/useActiveStore'
import type { Quote, SaleResult } from '@/lib/types'
import { useConnection } from '@/offline/connection'
import { useAuthStore } from '@/stores/auth'
import { usePosStore } from '@/stores/pos'
import { useCartStore } from '@/stores/cart'
import { Cart } from './Cart'
import { OfflinePos } from './OfflinePos'
import { ReceiptNotice } from './ReceiptNotice'
import { saveSaleLocally } from './offlineSale'
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
  const { storeId, store } = useActiveStore()
  const online = useConnection((s) => s.online)
  const me = useAuthStore((s) => s.me)
  const [payments, setPayments] = useState<PaymentRow[]>([])
  const [done, setDone] = useState<Done | null>(null)
  const showReceipt = usePosStore((s) => s.show)

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
    mutationFn: async () => {
      try {
        const sale = await api<SaleResult>('/sales', 'POST', {
          idempotency_key: saleKey,
          store_id: storeId,
          customer_id: customer?.id ?? null,
          items,
          payments: payments.map((p) => ({
            method: p.method,
            amount: fromPaise(toPaise(p.amount) ?? 0),
            reference: p.method === 'cash' ? null : p.reference.trim(),
          })),
        })
        return { kind: 'online' as const, sale }
      } catch (e) {
        // The connection dropped during checkout. The sale may or may not have reached the server;
        // saving it under the same sale key makes either case safe (it is never booked twice).
        if (e instanceof ApiError && e.network && me && total) {
          const queued = await saveSaleLocally({
            saleKey,
            storeId,
            me,
            customer,
            lines,
            payments,
            total,
          })
          return { kind: 'offline' as const, queued }
        }
        throw e
      }
    },
    onSuccess: async (outcome) => {
      if (outcome.kind === 'offline') {
        showReceipt(outcome.queued, true)
        clear()
        setPayments([])
        return
      }
      const sale = outcome.sale
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

  // No connection: sell from the copy of the catalogue on this device.
  if (!online && storeId) return <OfflinePos storeId={storeId} storeName={store?.name ?? ''} />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ws-ink">Point of Sale</h1>
          <p className="text-sm text-ws-muted">Create a new customer transaction.</p>
        </div>
      </div>

      <ReceiptNotice storeName={store?.name ?? ''} />

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
