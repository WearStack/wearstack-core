import { Button } from '@/components/ui/button'
import { formatMoney } from '@/lib/format'
import type { QueuedSale } from '@/offline/db'

/**
 * The receipt for a sale made without a connection. It is NOT a GST tax invoice: the numbered
 * invoice is issued by the server when the sale syncs. The wording says so plainly.
 */
export function ProvisionalReceipt({
  sale,
  storeName,
  onDismiss,
}: {
  sale: QueuedSale
  storeName: string
  onDismiss: () => void
}) {
  return (
    <section
      id="receipt"
      aria-label="Provisional receipt"
      className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-ws-ink"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <b className="text-base">Provisional receipt · {sale.provisionalNumber}</b>
          <div className="text-xs text-ws-muted">
            {storeName} · {new Date(sale.soldAt).toLocaleString('en-IN')} · {sale.cashierName}
            {sale.customerName ? ` · ${sale.customerName}` : ''}
          </div>
        </div>
        <div className="flex gap-2 print:hidden">
          <Button size="sm" variant="outline" onClick={() => window.print()}>
            Print
          </Button>
          <Button size="sm" variant="outline" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
      </div>
      <table className="mt-3 w-full text-xs">
        <tbody>
          {sale.items.map((i) => (
            <tr key={i.variantId} className="border-t border-amber-200">
              <td className="py-1">
                {i.name} <span className="text-ws-muted">{i.label}</span>
              </td>
              <td className="py-1 text-right">
                {i.quantity} × {formatMoney(i.unitPrice)}
                {Number(i.discount) > 0 && ` − ${formatMoney(i.discount)}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex justify-between border-t border-amber-300 pt-2 text-base font-bold">
        <span>Total (GST included)</span>
        <span>{formatMoney(sale.total)}</span>
      </div>
      <div className="text-xs text-ws-muted">
        Paid:{' '}
        {sale.payments
          .map(
            (p) =>
              `${p.method.toUpperCase()} ${formatMoney(p.amount)}${p.reference ? ` (ref ${p.reference})` : ''}`,
          )
          .join(' · ')}
      </div>
      <p className="mt-3 rounded-md bg-white/70 p-2 text-xs">
        <b>This is not a GST tax invoice.</b> It is saved on this device and will be sent to the
        server when the connection is back. The numbered tax invoice is issued then.
      </p>
    </section>
  )
}
