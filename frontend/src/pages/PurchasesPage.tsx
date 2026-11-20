import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useDeferredValue, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { useActiveStore } from '@/lib/useActiveStore'
import { formatMoney } from '@/lib/format'
import { fromPaise, toPaise } from '@/lib/money'
import type { LookupVariant, Purchase, Supplier } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

interface Line {
  variantId: string
  name: string
  label: string
  qty: string
  cost: string
}

const today = () => new Date().toISOString().slice(0, 10)

function Suppliers({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', gstin: '', phone: '' })
  const suppliers = useQuery({
    queryKey: ['suppliers'],
    queryFn: () => api<Supplier[]>('/suppliers'),
  })
  const add = useMutation({
    mutationFn: () =>
      api('/suppliers', 'POST', { name: f.name, gstin: f.gstin || null, phone: f.phone || null }),
    onSuccess: () => {
      setF({ name: '', gstin: '', phone: '' })
      void qc.invalidateQueries({ queryKey: ['suppliers'] })
    },
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-ws-ink">Suppliers</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-ws-muted">
          {suppliers.data?.map((s) => s.name).join(', ') || 'None yet'}
        </p>
        {canWrite && (
          <form
            className="grid gap-2 sm:grid-cols-4"
            onSubmit={(e) => {
              e.preventDefault()
              add.mutate()
            }}
          >
            <Input
              placeholder="Supplier name"
              required
              value={f.name}
              onChange={(e) => setF({ ...f, name: e.target.value })}
            />
            <Input
              placeholder="GSTIN (optional)"
              value={f.gstin}
              onChange={(e) => setF({ ...f, gstin: e.target.value })}
            />
            <Input
              placeholder="Phone (optional)"
              value={f.phone}
              onChange={(e) => setF({ ...f, phone: e.target.value })}
            />
            <Button
              type="submit"
              size="sm"
              className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
            >
              Add supplier
            </Button>
          </form>
        )}
        {add.isError && <p className="text-destructive text-sm">{add.error.message}</p>}
      </CardContent>
    </Card>
  )
}

function NewPurchase({ storeId }: { storeId: string }) {
  const qc = useQueryClient()
  const suppliers = useQuery({
    queryKey: ['suppliers'],
    queryFn: () => api<Supplier[]>('/suppliers'),
  })
  const [supplierId, setSupplierId] = useState('')
  const [bill, setBill] = useState('')
  const [date, setDate] = useState(today())
  const [lines, setLines] = useState<Line[]>([])
  const [q, setQ] = useState('')
  const deferred = useDeferredValue(q.trim())
  const results = useQuery({
    queryKey: ['lookup', storeId, deferred],
    enabled: deferred.length >= 2,
    queryFn: () =>
      api<LookupVariant[]>(
        `/variants/lookup?q=${encodeURIComponent(deferred)}&store_id=${storeId}`,
      ),
  })

  const linePaise = (l: Line) => {
    const cost = toPaise(l.cost)
    const qty = Number(l.qty)
    return cost !== null && Number.isInteger(qty) && qty > 0 ? cost * qty : null
  }
  const valid =
    !!supplierId && !!bill.trim() && lines.length > 0 && lines.every((l) => linePaise(l) !== null)
  const total = lines.reduce((s, l) => s + (linePaise(l) ?? 0), 0)

  const save = useMutation({
    mutationFn: () =>
      api('/purchases', 'POST', {
        store_id: storeId,
        supplier_id: supplierId,
        bill_number: bill,
        bill_date: date,
        items: lines.map((l) => ({
          variant_id: l.variantId,
          quantity: Number(l.qty),
          unit_cost: fromPaise(toPaise(l.cost) ?? 0),
        })),
      }),
    onSuccess: () => {
      setLines([])
      setBill('')
      setQ('')
      void qc.invalidateQueries({ queryKey: ['purchases'] })
    },
  })
  const addVariant = (v: LookupVariant) => {
    if (lines.some((l) => l.variantId === v.variant_id)) return
    setLines([
      ...lines,
      {
        variantId: v.variant_id,
        name: v.product_name,
        label: [v.size, v.colour].filter(Boolean).join(' / ') || 'Default',
        qty: '1',
        cost: '',
      },
    ])
    setQ('')
  }
  const setLine = (id: string, patch: Partial<Line>) =>
    setLines(lines.map((l) => (l.variantId === id ? { ...l, ...patch } : l)))
  const field = (label: string, input: React.ReactNode) => (
    <label className="block space-y-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      {input}
    </label>
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-ws-ink">New purchase</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          {field(
            'Supplier',
            <select
              className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-sm"
              value={supplierId}
              onChange={(e) => setSupplierId(e.target.value)}
            >
              <option value="">Select…</option>
              {suppliers.data
                ?.filter((s) => s.is_active)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>,
          )}
          {field(
            'Supplier bill number',
            <Input value={bill} onChange={(e) => setBill(e.target.value)} />,
          )}
          {field(
            'Bill date',
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />,
          )}
        </div>
        <div className="space-y-1">
          <Input
            placeholder="Search a product or SKU to add…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {deferred.length >= 2 && (
            <ul className="rounded-md border border-ws-line text-sm">
              {results.data?.map((v) => (
                <li key={v.variant_id}>
                  <button
                    type="button"
                    className="w-full px-3 py-2 text-left hover:bg-ws-bg"
                    onClick={() => addVariant(v)}
                  >
                    {v.product_name} · {[v.size, v.colour].filter(Boolean).join(' / ') || 'Default'}{' '}
                    · {v.sku}
                  </button>
                </li>
              ))}
              {results.data?.length === 0 && (
                <li className="px-3 py-2 text-ws-muted">No matching products.</li>
              )}
            </ul>
          )}
        </div>
        {lines.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>Unit cost ₹</TableHead>
                <TableHead>Line total</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((l) => (
                <TableRow key={l.variantId}>
                  <TableCell>
                    {l.name} · {l.label}
                  </TableCell>
                  <TableCell>
                    <Input
                      className="h-8 w-20"
                      inputMode="numeric"
                      aria-label={`Quantity for ${l.name} ${l.label}`}
                      value={l.qty}
                      onChange={(e) => setLine(l.variantId, { qty: e.target.value })}
                    />
                  </TableCell>
                  <TableCell>
                    <Input
                      className="h-8 w-28"
                      inputMode="decimal"
                      aria-label={`Unit cost for ${l.name} ${l.label}`}
                      value={l.cost}
                      onChange={(e) => setLine(l.variantId, { cost: e.target.value })}
                    />
                  </TableCell>
                  <TableCell>
                    {linePaise(l) === null ? '—' : formatMoney(fromPaise(linePaise(l) ?? 0))}
                  </TableCell>
                  <TableCell>
                    <button
                      className="text-xs text-ws-muted hover:text-red-600"
                      aria-label="Remove line"
                      onClick={() => setLines(lines.filter((x) => x !== l))}
                    >
                      ✕
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <div className="flex items-center justify-between">
          <span className="text-sm text-ws-muted">
            Bill total: <b className="text-ws-ink">{formatMoney(fromPaise(total))}</b>
          </span>
          <Button
            disabled={!valid || save.isPending}
            onClick={() => save.mutate()}
            className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
          >
            Save as draft
          </Button>
        </div>
        {save.isError && <p className="text-destructive text-sm">{save.error.message}</p>}
        <p className="text-xs text-ws-muted">
          A draft does not change stock. Receive it below once the goods arrive.
        </p>
      </CardContent>
    </Card>
  )
}

export function PurchasesPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.can('purchase:write'))
  const suppliers = useQuery({
    queryKey: ['suppliers'],
    queryFn: () => api<Supplier[]>('/suppliers'),
  })
  const [open, setOpen] = useState<string | null>(null)
  const { storeId } = useActiveStore()
  const purchases = useQuery({
    queryKey: ['purchases', storeId],
    enabled: !!storeId,
    queryFn: () => api<Purchase[]>(`/purchases?store_id=${storeId}&limit=100`),
  })
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['purchases'] })
    void qc.invalidateQueries({ queryKey: ['stock'] })
  }
  const receive = useMutation({
    mutationFn: (id: string) => api(`/purchases/${id}/receive`, 'POST'),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/purchases/${id}`, 'DELETE'),
    onSuccess: refresh,
  })
  const supplierName = (id: string) => suppliers.data?.find((s) => s.id === id)?.name ?? '—'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ws-ink">Purchases</h1>
          <p className="text-sm text-ws-muted">Supplier bills and goods receiving.</p>
        </div>
      </div>
      <div className="rounded-xl border border-ws-line bg-white p-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bill</TableHead>
              <TableHead>Supplier</TableHead>
              <TableHead>Date</TableHead>
              <TableHead>Total</TableHead>
              <TableHead>Status</TableHead>
              {canWrite && <TableHead />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {purchases.data?.map((p) => (
              <Fragment key={p.id}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setOpen(open === p.id ? null : p.id)}
                >
                  <TableCell className="font-medium text-ws-ink">{p.bill_number}</TableCell>
                  <TableCell>{supplierName(p.supplier_id)}</TableCell>
                  <TableCell>{p.bill_date}</TableCell>
                  <TableCell>{formatMoney(p.total)}</TableCell>
                  <TableCell>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-bold ${p.status === 'draft' ? 'bg-[#fff0e3] text-[#a84e0d]' : 'bg-green-100 text-green-800'}`}
                    >
                      {p.status}
                    </span>
                  </TableCell>
                  {canWrite && (
                    <TableCell
                      className="space-x-2 text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {p.status === 'draft' && (
                        <>
                          <Button
                            size="sm"
                            onClick={() => receive.mutate(p.id)}
                            className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
                          >
                            Receive
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => remove.mutate(p.id)}>
                            Delete
                          </Button>
                        </>
                      )}
                    </TableCell>
                  )}
                </TableRow>
                {open === p.id && (
                  <TableRow>
                    <TableCell colSpan={6} className="bg-ws-bg">
                      <ul className="space-y-1 text-xs">
                        {p.items.map((i) => (
                          <li key={i.variant_id} className="flex justify-between">
                            <span>
                              {i.product_name} · {i.variant_label} · {i.sku}
                            </span>
                            <span>
                              {i.quantity} × {formatMoney(i.unit_cost)} ={' '}
                              {formatMoney(i.line_total)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
        {purchases.data?.length === 0 && (
          <p className="py-6 text-center text-sm text-ws-muted">No purchases yet.</p>
        )}
        {(receive.isError || remove.isError) && (
          <p className="text-destructive text-sm">{(receive.error ?? remove.error)?.message}</p>
        )}
      </div>
      {canWrite && storeId && <NewPurchase storeId={storeId} />}
      <Suppliers canWrite={canWrite} />
    </div>
  )
}
