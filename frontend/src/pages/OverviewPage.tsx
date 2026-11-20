import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BarChart } from '@/features/reports/BarChart'
import { api } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { Overview, OverviewRange, StockRow } from '@/lib/types'
import { useActiveStore } from '@/lib/useActiveStore'
import { useAuthStore } from '@/stores/auth'

const RANGES: { id: OverviewRange; label: string; versus: string }[] = [
  { id: 'today', label: 'Today', versus: 'yesterday' },
  { id: 'week', label: 'This week', versus: 'last week' },
  { id: 'month', label: 'This month', versus: 'last month' },
]

export function OverviewPage() {
  const navigate = useNavigate()
  const { me, can } = useAuthStore()
  const { storeId } = useActiveStore()
  const [range, setRange] = useState<OverviewRange>('today')
  const canReport = can('report:read')
  const canSell = can('sale:create')
  const versus = RANGES.find((r) => r.id === range)?.versus ?? ''

  const overview = useQuery({
    queryKey: ['overview', range, storeId],
    enabled: canReport && !!storeId,
    queryFn: () => api<Overview>(`/reports/overview?range=${range}&store_id=${storeId}`),
  })
  const alerts = useQuery({
    queryKey: ['stock', 'alerts', storeId],
    enabled: can('inventory:read') && !!storeId,
    queryFn: () =>
      api<StockRow[]>(`/inventory?store_id=${storeId}&low_stock=true&sort=stock&limit=8`),
  })
  const o = overview.data

  return (
    <div className="space-y-5">
      <section className="flex min-h-[145px] items-center justify-between gap-4 rounded-2xl bg-[#fff0e3] px-6 py-6 sm:px-8">
        <div>
          <h1 className="text-[25px] leading-[1.1] font-bold text-[#174f9e] sm:text-[35px]">
            Your store. <span className="text-[#f47721]">Your style.</span>
          </h1>
          <p className="mt-2 mb-3 text-[#526681]">
            Everything your clothing business needs, in one place.
          </p>
          {canSell && (
            <button
              onClick={() => navigate('/pos')}
              className="rounded-lg bg-ws-orange px-3.5 py-2.5 font-bold text-[#172d50]"
            >
              Start a new sale →
            </button>
          )}
        </div>
        <div
          aria-hidden
          className="hidden shrink-0 rounded-[20px] bg-gradient-to-br from-[#ffb36f] to-ws-orange p-4 text-[40px] sm:block sm:text-[60px]"
        >
          🧥 👕 🛍️
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[23px] font-bold text-ws-ink">Overview</h2>
          <p className="text-xs text-ws-muted">
            Welcome back, {me?.full_name}. Here's what's happening in your store.
          </p>
        </div>
        {canReport && (
          <select
            aria-label="Period"
            value={range}
            onChange={(e) => setRange(e.target.value as OverviewRange)}
            className="rounded-[9px] border border-ws-line bg-white px-3 py-2.5 text-ws-ink"
          >
            {RANGES.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {canReport && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Metric
            tone="orange"
            label="TOTAL REVENUE"
            value={o ? formatMoney(o.revenue) : '—'}
            foot={growth(o?.revenue_growth, versus)}
          />
          <Metric
            tone="blue"
            label="TOTAL ORDERS"
            value={o ? String(o.orders) : '—'}
            foot={growth(o?.orders_growth, versus)}
          />
          <Metric
            label="ACTIVE PRODUCTS"
            value={o ? String(o.active_products) : '—'}
            foot="Across all categories"
          />
          <Link to="/inventory" className="block">
            <Metric
              tone="peach"
              label="LOW STOCK ITEMS"
              value={o ? String(o.low_stock_items) : '—'}
              foot="Products need attention"
            />
          </Link>
        </div>
      )}
      {overview.isError && (
        <p className="text-destructive text-sm" role="alert">
          {overview.error.message}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        {canReport && o && (
          <BarChart
            title="Sales performance"
            labels={o.series.points.map((p) => p.label)}
            values={o.series.points.map((p) => Number(p.total))}
          />
        )}
        {(canSell || can('inventory:adjust')) && (
          <div className="rounded-xl border border-ws-line bg-white p-4">
            <h3 className="mb-3 text-sm font-semibold text-ws-ink">⚡ Quick actions</h3>
            {canSell && (
              <Link
                to="/pos"
                className="my-2.5 block rounded-[10px] bg-ws-orange p-4 font-bold text-[#172d50]"
              >
                🛒 &nbsp; New Sale →
              </Link>
            )}
            {can('inventory:adjust') && (
              <Link
                to="/inventory"
                className="my-2.5 block rounded-[10px] bg-ws-blue p-4 font-bold text-white"
              >
                ▣ &nbsp; Add Stock →
              </Link>
            )}
          </div>
        )}
      </div>

      {can('inventory:read') && (
        <div className="rounded-xl border border-ws-line bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-ws-ink">🔔 Inventory alerts</h3>
          {alerts.data?.length === 0 ? (
            <p className="py-3 text-sm text-ws-muted">
              Nothing needs attention. Set a reorder level on a product to be alerted when it runs
              low.
            </p>
          ) : (
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="text-left text-[10px] text-[#8290a3]">
                  <th className="p-2">PRODUCT</th>
                  <th className="p-2">SKU</th>
                  <th className="p-2">VARIANT</th>
                  <th className="p-2 text-right">STOCK</th>
                </tr>
              </thead>
              <tbody>
                {alerts.data?.map((r) => (
                  <tr key={r.variant_id} className="border-t border-[#edf1f6]">
                    <td className="p-3 font-bold">{r.product_name}</td>
                    <td className="p-3">{r.sku}</td>
                    <td className="p-3">{[r.size, r.colour].filter(Boolean).join(' / ') || '—'}</td>
                    <td className="p-3 text-right">
                      <span className="inline-block rounded-full bg-[#fff0e3] px-2.5 py-1 text-[10px] font-bold text-[#a84e0d]">
                        {r.quantity === 0 ? 'Out of stock' : `${r.quantity} left`}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

/** "↗ 18.6% growth" or "↘ 4.2% lower", with an honest message when there is nothing to compare. */
function growth(pct: string | null | undefined, versus: string): string {
  if (pct === undefined) return ' '
  if (pct === null) return `No sales ${versus} to compare with`
  const n = Number(pct)
  if (n === 0) return `Same as ${versus}`
  return `${n > 0 ? '↗' : '↘'} ${Math.abs(n)}% ${n > 0 ? 'growth' : 'lower'} vs ${versus}`
}

function Metric({
  label,
  value,
  foot,
  tone,
}: {
  label: string
  value: string
  foot: string
  tone?: 'orange' | 'blue' | 'peach'
}) {
  const palette = {
    orange: 'border-ws-orange bg-ws-orange text-ws-ink',
    blue: 'border-ws-blue bg-ws-blue text-white',
    peach: 'border-[#ffd8ba] bg-[#fff0e3] text-[#c95718]',
    none: 'border-ws-line bg-white text-ws-ink',
  }[tone ?? 'none']
  return (
    <div className={`min-h-[120px] rounded-[13px] border p-[18px] shadow-sm ${palette}`}>
      <div className="text-[11px] font-bold opacity-80">{label}</div>
      <strong className="my-2.5 block text-[28px]">{value}</strong>
      <div className="text-[11px] opacity-80">{foot}</div>
    </div>
  )
}
