import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatMoney } from '@/lib/format'
import type { Quote } from '@/lib/types'
import { useCartStore } from '@/stores/cart'
import { CustomerPicker } from './CustomerPicker'

/** What an offline till can show: the tax-inclusive total (the GST breakdown comes with the invoice). */
export interface OfflineTotals {
  subtotal: string
  roundOff: string
  grandTotal: string
}

interface Props {
  quote: Quote | undefined
  quoteError: string | null
  invalidDiscount: boolean
  offlineTotals?: OfflineTotals | null
  /** Replaces the customer search, which needs the server, with one that works offline. */
  customerSlot?: ReactNode
}

export function Cart({ quote, quoteError, invalidDiscount, offlineTotals, customerSlot }: Props) {
  const { lines, setQty, setDiscount, remove } = useCartStore()
  const count = lines.reduce((n, l) => n + l.qty, 0)

  return (
    <div className="rounded-xl border border-ws-line bg-white p-4">
      <h2 className="mb-3 flex items-center gap-2 font-semibold text-ws-ink">
        Current cart
        <span className="rounded-full bg-[#fff0e3] px-2 py-0.5 text-xs font-bold text-[#a84e0d]">
          {count} item{count === 1 ? '' : 's'}
        </span>
      </h2>
      {customerSlot ?? <CustomerPicker />}
      <ul className="mt-3 divide-y divide-ws-line">
        {lines.map((l) => (
          <li key={l.variantId} className="space-y-2 py-3">
            <div className="flex justify-between gap-2">
              <div>
                <b className="text-ws-ink">{l.name}</b>
                <div className="text-xs text-ws-muted">
                  {l.label} · {formatMoney(l.unitPrice)} each
                </div>
              </div>
              <button
                aria-label={`Remove ${l.name}`}
                className="text-xs text-ws-muted hover:text-red-600"
                onClick={() => remove(l.variantId)}
              >
                ✕
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  aria-label="Decrease quantity"
                  onClick={() => setQty(l.variantId, l.qty - 1)}
                >
                  −
                </Button>
                <span className="w-8 text-center" aria-label="Quantity">
                  {l.qty}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  aria-label="Increase quantity"
                  disabled={l.stock !== null && l.qty >= l.stock}
                  onClick={() => setQty(l.variantId, l.qty + 1)}
                >
                  +
                </Button>
              </div>
              <label className="flex items-center gap-1 text-xs text-ws-muted">
                Discount ₹
                <Input
                  className="h-8 w-20"
                  inputMode="decimal"
                  aria-label={`Discount for ${l.name}`}
                  value={l.discount}
                  onChange={(e) => setDiscount(l.variantId, e.target.value)}
                />
              </label>
            </div>
          </li>
        ))}
        {lines.length === 0 && <li className="py-4 text-sm text-ws-muted">No items added yet.</li>}
      </ul>

      {lines.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-ws-line pt-3 text-sm">
          {invalidDiscount && (
            <p className="text-destructive">Enter discounts as amounts like 50 or 49.50.</p>
          )}
          {quoteError && <p className="text-destructive">{quoteError}</p>}
          {offlineTotals && (
            <>
              <Row
                label="Round off"
                value={offlineTotals.roundOff}
                hide={offlineTotals.roundOff === '0.00'}
              />
              <div className="flex justify-between border-t border-ws-line pt-2 text-base font-bold text-ws-ink">
                <span>Total (incl. GST)</span>
                <span>{formatMoney(offlineTotals.grandTotal)}</span>
              </div>
              <p className="text-xs text-ws-muted">
                GST is included in the price. The tax breakup appears on the final invoice.
              </p>
            </>
          )}
          {quote && (
            <>
              <Row
                label="Discount"
                value={quote.discount_total}
                hide={quote.discount_total === '0.00'}
              />
              <Row label="Taxable value" value={quote.taxable_total} />
              {quote.is_interstate ? (
                <Row label="IGST" value={quote.igst_total} />
              ) : (
                <>
                  <Row label="CGST" value={quote.cgst_total} />
                  <Row label="SGST" value={quote.sgst_total} />
                </>
              )}
              <Row label="Round off" value={quote.round_off} hide={quote.round_off === '0.00'} />
              <div className="flex justify-between border-t border-ws-line pt-2 text-base font-bold text-ws-ink">
                <span>Total (incl. GST)</span>
                <span>{formatMoney(quote.grand_total)}</span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, value, hide }: { label: string; value: string; hide?: boolean }) {
  if (hide) return null
  return (
    <div className="flex justify-between text-ws-muted">
      <span>{label}</span>
      <span>{formatMoney(value)}</span>
    </div>
  )
}
