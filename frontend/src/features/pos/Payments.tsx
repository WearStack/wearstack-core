import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatMoney } from '@/lib/format'
import { fromPaise, newId, toPaise } from '@/lib/money'
import { paymentsPaise, type Method, type PaymentRow } from './paymentRules'

interface Props {
  rows: PaymentRow[]
  onChange: (rows: PaymentRow[]) => void
  total: string | undefined
}

export function Payments({ rows, onChange, total }: Props) {
  const totalPaise = total ? toPaise(total) : null
  const paid = paymentsPaise(rows)
  const remaining = totalPaise !== null && paid !== null ? totalPaise - paid : null
  const update = (id: string, patch: Partial<PaymentRow>) =>
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  const add = (method: Method) =>
    onChange([
      ...rows,
      {
        id: newId(),
        method,
        amount: remaining && remaining > 0 ? fromPaise(remaining) : '',
        reference: '',
      },
    ])

  return (
    <div className="rounded-xl border border-ws-line bg-white p-4">
      <h2 className="mb-3 font-semibold text-ws-ink">Payment</h2>
      <div className="mb-3 flex gap-2">
        {(['cash', 'upi', 'card'] as const).map((m) => (
          <Button key={m} size="sm" variant="outline" disabled={!total} onClick={() => add(m)}>
            + {m.toUpperCase()}
          </Button>
        ))}
      </div>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2">
            <span className="w-12 text-xs font-bold text-ws-ink">{r.method.toUpperCase()}</span>
            <Input
              className="w-28"
              inputMode="decimal"
              aria-label={`${r.method} amount`}
              placeholder="Amount"
              value={r.amount}
              onChange={(e) => update(r.id, { amount: e.target.value })}
            />
            {r.method !== 'cash' && (
              <Input
                className="w-44"
                aria-label={`${r.method} reference`}
                placeholder={r.method === 'upi' ? 'UPI transaction ID' : 'Approval code'}
                value={r.reference}
                onChange={(e) => update(r.id, { reference: e.target.value })}
              />
            )}
            <button
              className="text-xs text-ws-muted hover:text-red-600"
              aria-label="Remove payment"
              onClick={() => onChange(rows.filter((x) => x.id !== r.id))}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      {rows.some((r) => r.method !== 'cash') && (
        <p className="mt-2 text-xs text-ws-muted">
          Confirm UPI and card payments on the device first, then enter the reference shown there.
        </p>
      )}
      <div className="mt-3 flex justify-between text-sm">
        <span className="text-ws-muted">
          {remaining !== null && remaining < 0 ? 'Over by' : 'Remaining'}
        </span>
        <b className={remaining === 0 ? 'text-green-700' : 'text-ws-ink'}>
          {remaining === null ? '—' : formatMoney(fromPaise(Math.abs(remaining)))}
        </b>
      </div>
    </div>
  )
}
