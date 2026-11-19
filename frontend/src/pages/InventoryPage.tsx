import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import type { Movement, StockRow, Store } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

function RowPanel({
  row,
  storeId,
  canAdjust,
}: {
  row: StockRow
  storeId: string
  canAdjust: boolean
}) {
  const qc = useQueryClient()
  const [qty, setQty] = useState('')
  const [reason, setReason] = useState('')
  const [level, setLevel] = useState(String(row.reorder_level))
  const history = useQuery({
    queryKey: ['movements', storeId, row.variant_id],
    queryFn: () =>
      api<Movement[]>(
        `/inventory/movements?store_id=${storeId}&variant_id=${row.variant_id}&limit=20`,
      ),
  })
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['stock'] })
    void qc.invalidateQueries({ queryKey: ['movements', storeId, row.variant_id] })
  }
  // The first stock entry for a variant is its opening balance; later changes are adjustments.
  const isOpening = !history.isLoading && history.data?.length === 0
  const move = useMutation({
    mutationFn: () =>
      api('/inventory/movements', 'POST', {
        store_id: storeId,
        variant_id: row.variant_id,
        kind: isOpening ? 'opening' : 'adjustment',
        quantity: Number(qty),
        reason: reason || null,
      }),
    onSuccess: () => {
      setQty('')
      setReason('')
      refresh()
    },
  })
  const saveLevel = useMutation({
    mutationFn: () =>
      api('/inventory/reorder-level', 'PUT', {
        store_id: storeId,
        variant_id: row.variant_id,
        reorder_level: Number(level),
      }),
    onSuccess: refresh,
  })

  return (
    <div className="grid gap-6 sm:grid-cols-2">
      {canAdjust && (
        <div className="space-y-3">
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault()
              move.mutate()
            }}
          >
            <h4 className="text-sm font-semibold text-ws-ink">
              {isOpening ? 'Set opening stock' : 'Adjust stock'}
            </h4>
            <Input
              className="block"
              type="number"
              step={1}
              min={isOpening ? 1 : undefined}
              placeholder={isOpening ? 'Quantity' : 'Change, e.g. -2 or 5'}
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              required
            />
            {!isOpening && (
              <Input
                className="block"
                placeholder="Reason (required)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                required
              />
            )}
            <div>
              <Button
                type="submit"
                size="sm"
                disabled={move.isPending}
                className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
              >
                Save
              </Button>
            </div>
            {move.isError && <p className="text-destructive text-xs">{move.error.message}</p>}
          </form>
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              saveLevel.mutate()
            }}
          >
            <div className="space-y-1">
              <label htmlFor={`reorder-${row.variant_id}`} className="text-xs text-ws-muted">
                Reorder level
              </label>
              <Input
                id={`reorder-${row.variant_id}`}
                type="number"
                min={0}
                value={level}
                onChange={(e) => setLevel(e.target.value)}
                className="w-28"
              />
            </div>
            <Button type="submit" size="sm" variant="outline">
              Set
            </Button>
          </form>
        </div>
      )}
      <div>
        <h4 className="mb-2 text-sm font-semibold text-ws-ink">History</h4>
        <ul className="space-y-1 text-xs">
          {history.data?.map((m) => (
            <li key={m.id} className="flex justify-between gap-3 border-b border-ws-line py-1">
              <span>
                {new Date(m.created_at).toLocaleString('en-IN')} · {m.movement_type}
                {m.reason ? ` · ${m.reason}` : ''}
              </span>
              <span className={m.quantity_delta < 0 ? 'text-red-600' : 'text-green-700'}>
                {m.quantity_delta > 0 ? '+' : ''}
                {m.quantity_delta} → {m.balance_after}
              </span>
            </li>
          ))}
          {history.data?.length === 0 && <li className="text-ws-muted">No movements yet.</li>}
        </ul>
      </div>
    </div>
  )
}

export function InventoryPage() {
  const canAdjust = useAuthStore((s) => s.can('inventory:adjust'))
  const stores = useQuery({ queryKey: ['stores'], queryFn: () => api<Store[]>('/stores') })
  const [chosen, setChosen] = useState('')
  const storeId = chosen || stores.data?.[0]?.id || ''
  const [q, setQ] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const stock = useQuery({
    queryKey: ['stock', storeId, q, lowOnly],
    enabled: !!storeId,
    queryFn: () =>
      api<StockRow[]>(
        `/inventory?store_id=${storeId}&limit=500${q ? `&q=${encodeURIComponent(q)}` : ''}${lowOnly ? '&low_stock=true' : ''}`,
      ),
  })

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-ws-ink">Inventory</h1>
        <p className="text-sm text-ws-muted">Monitor stock levels across your catalogue.</p>
      </div>
      <div className="rounded-xl border border-ws-line bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <select
            className="border-input h-9 rounded-md border bg-transparent px-2 text-sm"
            value={storeId}
            onChange={(e) => setChosen(e.target.value)}
          >
            {stores.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <Input
            className="max-w-xs"
            placeholder="Search name, SKU or barcode…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={lowOnly}
              onChange={(e) => setLowOnly(e.target.checked)}
            />
            Low stock only
          </label>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead>Variant</TableHead>
              <TableHead>SKU</TableHead>
              <TableHead>Stock</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {stock.data?.map((r) => (
              <Fragment key={r.variant_id}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setOpen(open === r.variant_id ? null : r.variant_id)}
                >
                  <TableCell className="font-medium text-ws-ink">{r.product_name}</TableCell>
                  <TableCell>
                    {[r.size, r.colour].filter(Boolean).join(' / ') || 'Default'}
                  </TableCell>
                  <TableCell>{r.sku}</TableCell>
                  <TableCell>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-bold ${r.low_stock ? 'bg-[#fff0e3] text-[#a84e0d]' : 'bg-ws-bg text-ws-ink'}`}
                    >
                      {r.quantity}
                      {r.low_stock && (r.quantity === 0 ? ' · out' : ' · low')}
                    </span>
                  </TableCell>
                </TableRow>
                {open === r.variant_id && (
                  <TableRow>
                    <TableCell colSpan={4} className="bg-ws-bg">
                      <RowPanel row={r} storeId={storeId} canAdjust={canAdjust} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
        {stock.data?.length === 0 && (
          <p className="py-6 text-center text-sm text-ws-muted">Nothing to show.</p>
        )}
        {stock.isError && <p className="text-destructive text-sm">Could not load stock.</p>}
      </div>
    </div>
  )
}
