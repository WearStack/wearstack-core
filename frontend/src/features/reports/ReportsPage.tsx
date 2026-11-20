import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { ReportData, Store } from '@/lib/types'
import { BarChart } from './BarChart'
import { downloadFile } from './download'
import { ReportTable } from './ReportTable'

type Tab = 'sales' | 'gst' | 'top-products' | 'stock' | 'purchases'
const TABS: { id: Tab; label: string }[] = [
  { id: 'sales', label: 'Sales' },
  { id: 'gst', label: 'GST' },
  { id: 'top-products', label: 'Top products' },
  { id: 'stock', label: 'Stock' },
  { id: 'purchases', label: 'Purchases' },
]

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return iso(d)
}
const SELECT = 'border-input h-9 rounded-md border bg-white px-2 text-sm'

export function ReportsPage() {
  const [tab, setTab] = useState<Tab>('sales')
  const [from, setFrom] = useState(daysAgo(29))
  const [to, setTo] = useState(daysAgo(0))
  const [group, setGroup] = useState('day')
  const [storeId, setStoreId] = useState('')
  const [rank, setRank] = useState('quantity')
  const [breakdown, setBreakdown] = useState('period')
  const [lowOnly, setLowOnly] = useState(false)
  const [hideZero, setHideZero] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const stores = useQuery({ queryKey: ['stores'], queryFn: () => api<Store[]>('/stores') })

  const params = new URLSearchParams()
  if (tab !== 'stock') {
    params.set('from', from)
    params.set('to', to)
  }
  if (storeId) params.set('store_id', storeId)
  if (tab === 'sales' || tab === 'purchases') params.set('group', group)
  if (tab === 'top-products') params.set('rank', rank)
  if (tab === 'purchases') params.set('breakdown', breakdown)
  if (tab === 'stock') {
    if (lowOnly) params.set('low_only', 'true')
    if (hideZero) params.set('hide_zero', 'true')
  }
  const query = params.toString()
  const report = useQuery({
    queryKey: ['report', tab, query],
    queryFn: () => api<ReportData>(`/reports/${tab}?${query}`),
    retry: false,
  })

  const download = async (ext: 'csv' | 'pdf') => {
    setBusy(ext)
    setDownloadError(null)
    try {
      const span = tab === 'stock' ? '' : `-${from}_to_${to}`
      await downloadFile(`/reports/${tab}.${ext}?${query}`, `${tab}${span}.${ext}`)
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setBusy(null)
    }
  }

  const preset = (days: number) => {
    setFrom(daysAgo(days))
    setTo(daysAgo(0))
  }
  const meta = report.data?.meta ?? {}
  const salesRows = tab === 'sales' ? (report.data?.rows ?? []) : []

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-ws-ink">Reports</h1>
        <p className="text-sm text-ws-muted">Sales, GST, stock and purchases for your stores.</p>
      </div>

      <div role="tablist" className="flex flex-wrap gap-1 border-b border-ws-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? 'border-ws-orange text-ws-ink' : 'border-transparent text-ws-muted'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-ws-line bg-white p-3">
        {tab !== 'stock' && (
          <>
            <label className="space-y-1 text-xs text-ws-muted">
              From
              <input
                type="date"
                className={`${SELECT} block`}
                value={from}
                max={to}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label className="space-y-1 text-xs text-ws-muted">
              To
              <input
                type="date"
                className={`${SELECT} block`}
                value={to}
                min={from}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
            <div className="flex gap-1">
              <Button size="sm" variant="outline" onClick={() => preset(0)}>
                Today
              </Button>
              <Button size="sm" variant="outline" onClick={() => preset(6)}>
                7 days
              </Button>
              <Button size="sm" variant="outline" onClick={() => preset(29)}>
                30 days
              </Button>
            </div>
          </>
        )}
        {(tab === 'sales' || tab === 'purchases') && (
          <label className="space-y-1 text-xs text-ws-muted">
            Group by
            <select
              className={`${SELECT} block`}
              value={group}
              onChange={(e) => setGroup(e.target.value)}
            >
              <option value="day">Day</option>
              <option value="week">Week</option>
              <option value="month">Month</option>
            </select>
          </label>
        )}
        {tab === 'top-products' && (
          <label className="space-y-1 text-xs text-ws-muted">
            Rank by
            <select
              className={`${SELECT} block`}
              value={rank}
              onChange={(e) => setRank(e.target.value)}
            >
              <option value="quantity">Units sold</option>
              <option value="revenue">Revenue</option>
            </select>
          </label>
        )}
        {tab === 'purchases' && (
          <label className="space-y-1 text-xs text-ws-muted">
            Show
            <select
              className={`${SELECT} block`}
              value={breakdown}
              onChange={(e) => setBreakdown(e.target.value)}
            >
              <option value="period">By period</option>
              <option value="supplier">By supplier</option>
            </select>
          </label>
        )}
        {tab === 'stock' && (
          <>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={lowOnly}
                onChange={(e) => setLowOnly(e.target.checked)}
              />
              Low stock only
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={hideZero}
                onChange={(e) => setHideZero(e.target.checked)}
              />
              Hide zero stock
            </label>
          </>
        )}
        {(stores.data?.length ?? 0) > 1 && (
          <label className="space-y-1 text-xs text-ws-muted">
            Store
            <select
              className={`${SELECT} block`}
              value={storeId}
              onChange={(e) => setStoreId(e.target.value)}
            >
              <option value="">All stores</option>
              {stores.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="ml-auto flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!report.data || busy !== null}
            onClick={() => download('csv')}
          >
            {busy === 'csv' ? 'Preparing…' : 'Download CSV'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!report.data || busy !== null}
            onClick={() => download('pdf')}
          >
            {busy === 'pdf' ? 'Preparing…' : 'Download PDF'}
          </Button>
        </div>
      </div>
      {downloadError && <p className="text-destructive text-sm">{downloadError}</p>}

      {report.isError && (
        <p className="text-destructive text-sm" role="alert">
          {report.error.message}
        </p>
      )}
      {report.isLoading && <p className="text-sm text-ws-muted">Loading…</p>}

      {report.data && tab === 'sales' && report.data.totals && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="Total billed" value={formatMoney(report.data.totals.total)} tone="orange" />
          <Kpi label="Orders" value={String(report.data.totals.orders)} tone="blue" />
          <Kpi label="Average order" value={formatMoney(String(meta.average_order_value ?? 0))} />
          <Kpi
            label="Gross margin"
            value={formatMoney(report.data.totals.margin)}
            sub={`${String(meta.margin_percent ?? 0)}% of taxable sales`}
          />
        </div>
      )}
      {tab === 'sales' && Number(meta.lines_without_cost ?? 0) > 0 && (
        <p className="rounded-md bg-[#fff0e3] p-3 text-sm text-[#a84e0d]" role="status">
          {String(meta.lines_without_cost)} sold line(s) have no cost price recorded, so gross
          margin is overstated. Add cost prices to your products or record purchases.
        </p>
      )}
      {salesRows.length > 1 && (
        <BarChart
          title="Total billed"
          labels={salesRows.map((r) => String(r.period))}
          values={salesRows.map((r) => Number(r.total))}
        />
      )}
      {tab === 'sales' &&
        report.data &&
        Object.keys((meta.payments as object) ?? {}).length > 0 && (
          <p className="text-sm text-ws-muted">
            Payments:{' '}
            {Object.entries(meta.payments as Record<string, string>)
              .map(([m, a]) => `${m.toUpperCase()} ${formatMoney(a)}`)
              .join(' · ')}
          </p>
        )}

      {report.data && (
        <div className="overflow-x-auto rounded-xl border border-ws-line bg-white p-2">
          <ReportTable report={report.data} />
          {report.data.rows.length === 0 && (
            <p className="py-6 text-center text-sm text-ws-muted">No data for this selection.</p>
          )}
        </div>
      )}
      {typeof meta.note === 'string' && <p className="text-xs text-ws-muted">{meta.note}</p>}
    </div>
  )
}

function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'orange' | 'blue'
}) {
  const palette =
    tone === 'orange'
      ? 'border-ws-orange bg-ws-orange text-ws-ink'
      : tone === 'blue'
        ? 'border-ws-blue bg-ws-blue text-white'
        : 'border-ws-line bg-white text-ws-ink'
  return (
    <div className={`rounded-xl border p-4 ${palette}`}>
      <div className="text-xs font-bold opacity-80">{label.toUpperCase()}</div>
      <div className="mt-2 text-2xl font-bold">{value}</div>
      {sub && <div className="text-xs opacity-80">{sub}</div>}
    </div>
  )
}
