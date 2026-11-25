import { useLiveQuery } from 'dexie-react-hooks'
import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { fromPaise } from '@/lib/money'
import { getCatalogMeta } from '@/offline/catalog'
import { useOfflineSummary } from '@/offline/hooks'
import { computeTotals, discountProblem } from '@/offline/rules'
import { useAuthStore } from '@/stores/auth'
import { useCartStore } from '@/stores/cart'
import { usePosStore } from '@/stores/pos'
import { Cart } from './Cart'
import { LocalCustomerPicker } from './LocalCustomerPicker'
import { OfflineSearch } from './OfflineSearch'
import { Payments } from './Payments'
import { paymentsReady, type PaymentRow } from './paymentRules'
import { saveSaleLocally } from './offlineSale'
import { ReceiptNotice } from './ReceiptNotice'

/** The till when there is no connection: sells from the copy of the catalogue on this device. */
export function OfflinePos({ storeId, storeName }: { storeId: string; storeName: string }) {
  const { me, can } = useAuthStore()
  const { lines, customer, saleKey, clear } = useCartStore()
  const [payments, setPayments] = useState<PaymentRow[]>([])
  const showReceipt = usePosStore((s) => s.show)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const { health, catalogHoursOld, pending } = useOfflineSummary(storeId)
  const meta = useLiveQuery(() => getCatalogMeta(), [])

  const basket = lines.map((l) => ({
    unitPrice: l.unitPrice,
    quantity: l.qty,
    discount: l.discount,
  }))
  const totals = useMemo(() => computeTotals(basket), [basket])
  const problem = discountProblem(
    basket,
    meta?.settings.freeDiscountPercent ?? 10,
    can('sale:discount'),
  )
  const blocked = health === 'missing' || health === 'expired'
  const total = totals ? fromPaise(totals.grandTotalPaise) : undefined
  const canComplete =
    !blocked &&
    !problem &&
    !!totals &&
    lines.length > 0 &&
    paymentsReady(payments, totals.grandTotalPaise) &&
    !saving

  const complete = async () => {
    if (!me || !total) return
    setSaving(true)
    setError(null)
    try {
      const sale = await saveSaleLocally({ saleKey, storeId, me, customer, lines, payments, total })
      showReceipt(sale, false)
      clear()
      setPayments([])
    } catch {
      setError('Could not save the sale on this device. Check the browser has storage available.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-ws-ink">Point of Sale</h1>
        <p className="text-sm text-ws-muted">Create a new customer transaction.</p>
      </div>

      <div
        role="status"
        className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
      >
        <b>You are offline.</b> Sales are saved on this device
        {pending > 0 ? ` (${pending} waiting)` : ''} and sent automatically when the connection
        returns. Receipts are provisional until then.
      </div>
      {health === 'missing' && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          This device has not downloaded the catalogue yet, so it cannot sell offline. Connect once
          to set it up.
        </p>
      )}
      {health === 'expired' && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          The catalogue on this device is {Math.round(catalogHoursOld ?? 0)} hours old, too old to
          sell from safely (prices and stock may have changed). Connect to refresh it.
        </p>
      )}
      {health === 'stale' && (
        <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">
          The catalogue is {Math.round(catalogHoursOld ?? 0)} hours old. Prices or stock may have
          changed; changed prices are reviewed by a manager when the sale syncs.
        </p>
      )}

      <ReceiptNotice storeName={storeName} />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <OfflineSearch blocked={blocked} />
        <div className="space-y-4">
          <Cart
            quote={undefined}
            quoteError={null}
            invalidDiscount={false}
            offlineTotals={
              totals
                ? {
                    subtotal: fromPaise(totals.subtotalPaise),
                    roundOff: fromPaise(totals.roundOffPaise),
                    grandTotal: fromPaise(totals.grandTotalPaise),
                  }
                : null
            }
            customerSlot={<LocalCustomerPicker />}
          />
          {problem && lines.length > 0 && <p className="text-destructive text-sm">{problem}</p>}
          {lines.length > 0 && (
            <>
              <Payments rows={payments} onChange={setPayments} total={total} />
              {error && <p className="text-destructive text-sm">{error}</p>}
              <div className="flex gap-2">
                <Button
                  className="grow bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
                  disabled={!canComplete}
                  onClick={complete}
                >
                  {saving ? 'Saving…' : 'Complete sale (offline)'}
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
    </div>
  )
}
