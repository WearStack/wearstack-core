import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { SyncOperationRow } from '@/lib/types'
import { useActiveStore } from '@/lib/useActiveStore'
import { refreshCatalog } from '@/offline/catalog'
import { ensureDevice } from '@/offline/device'
import { describeConflict, STATUS_LABEL, STATUS_STYLE } from '@/offline/describe'
import { useOfflineSummary } from '@/offline/hooks'
import { drainQueue } from '@/offline/syncEngine'
import { useAuthStore } from '@/stores/auth'
import { ResolvePanel } from './ResolvePanel'

const pill = (status: string) => (
  <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${STATUS_STYLE[status] ?? ''}`}>
    {STATUS_LABEL[status] ?? status}
  </span>
)

export function SyncPage() {
  const can = useAuthStore((s) => s.can)
  const { storeId, store } = useActiveStore()
  const { online, queue, pending, needsAttention, health, catalogHoursOld } =
    useOfflineSummary(storeId)
  const [busy, setBusy] = useState<'sync' | 'catalog' | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const manager = can('sync:resolve')

  // What needs a manager, across every device (only a manager can decide these).
  const held = useQuery({
    queryKey: ['sync-ops', storeId],
    enabled: manager && online && !!storeId,
    queryFn: async () => {
      const all = await api<SyncOperationRow[]>(`/sync/operations?store_id=${storeId}&limit=300`)
      return all.filter((o) => o.status === 'conflict' || o.status === 'failed')
    },
  })

  const syncNow = async () => {
    setBusy('sync')
    setMessage(null)
    try {
      const s = await drainQueue()
      setMessage(
        s.deferred && s.sent === 0
          ? online
            ? 'Nothing is waiting to be sent.'
            : 'Still offline: sales stay on this device until the connection returns.'
          : `Sent ${s.sent}: ${s.applied} synced, ${s.held} need attention.`,
      )
    } finally {
      setBusy(null)
    }
  }
  const refresh = async () => {
    setBusy('catalog')
    setMessage(null)
    try {
      await refreshCatalog(storeId, await ensureDevice(storeId))
      setMessage('Catalogue refreshed.')
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Could not refresh the catalogue.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ws-ink">Sync status</h1>
          <p className="text-sm text-ws-muted">
            Sales made on this device, and what became of them{store ? ` · ${store.name}` : ''}.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={busy !== null}
            onClick={syncNow}
            className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
          >
            {busy === 'sync' ? 'Sending…' : 'Sync now'}
          </Button>
          <Button size="sm" variant="outline" disabled={busy !== null || !online} onClick={refresh}>
            {busy === 'catalog' ? 'Refreshing…' : 'Refresh catalogue'}
          </Button>
        </div>
      </div>
      {message && (
        <p role="status" className="rounded-md bg-ws-bg p-3 text-sm text-ws-ink">
          {message}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="CONNECTION"
          value={online ? 'Online' : 'Offline'}
          tone={online ? 'good' : 'warn'}
        />
        <Stat label="WAITING TO SEND" value={String(pending)} tone={pending ? 'warn' : undefined} />
        <Stat
          label="NEED ATTENTION"
          value={String(needsAttention)}
          tone={needsAttention ? 'bad' : undefined}
        />
        <Stat
          label="CATALOGUE"
          value={
            catalogHoursOld === null ? 'Not downloaded' : `${Math.round(catalogHoursOld)} h old`
          }
          tone={health === 'fresh' ? 'good' : health === 'stale' ? 'warn' : 'bad'}
        />
      </div>

      {manager && (held.data?.length ?? 0) > 0 && (
        <section aria-label="Needs a manager" className="space-y-2">
          <h2 className="font-semibold text-ws-ink">Needs a manager ({held.data?.length})</h2>
          <p className="text-xs text-ws-muted">
            These sales already happened, so none are dropped. Each waits for your decision.
          </p>
          <ul className="space-y-2">
            {held.data?.map((op) => (
              <ResolvePanel key={op.id} op={op} />
            ))}
          </ul>
        </section>
      )}
      {manager && held.isSuccess && held.data.length === 0 && (
        <p className="text-sm text-ws-muted">No sales are waiting for a manager.</p>
      )}

      <section aria-label="This device" className="rounded-xl border border-ws-line bg-white p-4">
        <h2 className="mb-2 font-semibold text-ws-ink">On this device</h2>
        {queue.length === 0 ? (
          <p className="py-4 text-sm text-ws-muted">
            No offline sales have been made on this device.
          </p>
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-left text-[10px] text-[#8290a3]">
                <th className="p-2">RECEIPT</th>
                <th className="p-2">TIME</th>
                <th className="p-2">CASHIER</th>
                <th className="p-2 text-right">TOTAL</th>
                <th className="p-2">STATUS</th>
                <th className="p-2">DETAIL</th>
              </tr>
            </thead>
            <tbody>
              {queue.map((s) => (
                <tr key={s.localId} className="border-t border-[#edf1f6] align-top">
                  <td className="p-2 font-bold">{s.provisionalNumber}</td>
                  <td className="p-2">{new Date(s.soldAt).toLocaleString('en-IN')}</td>
                  <td className="p-2">{s.cashierName}</td>
                  <td className="p-2 text-right">{formatMoney(s.total)}</td>
                  <td className="p-2">{pill(s.status)}</td>
                  <td className="p-2">
                    {s.status === 'applied' && s.outcome?.invoiceNumber && (
                      <span>Invoice {s.outcome.invoiceNumber}</span>
                    )}
                    {s.status === 'pending' && s.lastError && (
                      <span className="text-ws-muted">Will retry · {s.lastError}</span>
                    )}
                    {s.outcome?.conflicts.map((c, i) => (
                      <div key={i}>{describeConflict(c)}</div>
                    ))}
                    {s.status === 'failed' && s.lastError && <span>{s.lastError}</span>}
                    {s.status === 'rejected' && <span>Rejected by a manager</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'good' | 'warn' | 'bad'
}) {
  const color =
    tone === 'good'
      ? 'text-green-700'
      : tone === 'warn'
        ? 'text-amber-700'
        : tone === 'bad'
          ? 'text-red-700'
          : 'text-ws-ink'
  return (
    <div className="rounded-xl border border-ws-line bg-white p-4">
      <div className="text-[11px] font-bold text-ws-muted">{label}</div>
      <div className={`mt-1 text-xl font-bold ${color}`}>{value}</div>
    </div>
  )
}
