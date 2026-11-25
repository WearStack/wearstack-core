import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { SyncOperationRow } from '@/lib/types'
import { describeConflict } from '@/offline/describe'

/** A manager's decision on one held sale: accept it as charged, reject it, or try again. */
export function ResolvePanel({ op }: { op: SyncOperationRow }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const detail = useQuery({
    queryKey: ['sync-op', op.id],
    queryFn: () => api<SyncOperationRow>(`/sync/operations/${op.id}`),
  })
  const decide = useMutation({
    mutationFn: (action: 'accept' | 'reject' | 'retry') =>
      api<SyncOperationRow>(`/sync/operations/${op.id}/resolve`, 'POST', {
        action,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['sync-ops'] })
      void qc.invalidateQueries({ queryKey: ['sync-op', op.id] })
      void qc.invalidateQueries({ queryKey: ['stock'] })
    },
  })
  const lines = detail.data?.lines ?? []
  const isConflict = op.status === 'conflict'

  return (
    <li className="space-y-2 rounded-lg border border-ws-line bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b className="text-ws-ink">
          {op.provisional_number ?? 'Offline sale'} · {formatMoney(op.total)}
        </b>
        <span className="text-xs text-ws-muted">
          {new Date(op.sold_at).toLocaleString('en-IN')} · {op.device_name} · {op.cashier_name}
        </span>
      </div>
      <ul className="list-disc pl-5 text-xs text-ws-ink">
        {op.conflicts.map((c, i) => (
          <li key={i}>{describeConflict(c)}</li>
        ))}
        {op.error_message && <li>{op.error_message}</li>}
      </ul>
      {lines.length > 0 && (
        <ul className="text-xs text-ws-muted">
          {lines.map((l, i) => (
            <li key={i}>
              {l.quantity} × {l.product_name} {l.variant_label} at {formatMoney(l.unit_price)}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="h-8 max-w-xs"
          placeholder="Note (required to reject)"
          aria-label={`Note for ${op.provisional_number ?? 'this sale'}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        {isConflict && (
          <Button
            size="sm"
            disabled={decide.isPending}
            onClick={() => decide.mutate('accept')}
            className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
          >
            Accept sale
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={decide.isPending}
          onClick={() => decide.mutate('retry')}
        >
          Try again
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={decide.isPending || !note.trim()}
          onClick={() => decide.mutate('reject')}
        >
          Reject
        </Button>
      </div>
      {isConflict && (
        <p className="text-xs text-ws-muted">
          Accepting books the sale as the customer was charged. If stock was short, a stock
          correction with a reason is added to the ledger.
        </p>
      )}
      {decide.isError && <p className="text-destructive text-xs">{decide.error.message}</p>}
    </li>
  )
}
