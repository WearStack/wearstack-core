import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { Overview } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

export function HomePage() {
  const me = useAuthStore((s) => s.me)
  const canReport = useAuthStore((s) => s.can('report:read'))
  const overview = useQuery({
    queryKey: ['overview'],
    enabled: canReport,
    queryFn: () => api<Overview>('/reports/overview'),
  })
  const o = overview.data
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-ws-ink">Welcome, {me?.full_name}</h1>
        <p className="mt-1 text-sm text-ws-muted">Here's what's happening in your store today.</p>
      </div>
      {o && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Card
            label="Revenue today"
            value={formatMoney(o.revenue)}
            className="border-ws-orange bg-ws-orange text-ws-ink"
          />
          <Card
            label="Orders today"
            value={String(o.orders)}
            className="border-ws-blue bg-ws-blue text-white"
          />
          <Card
            label="Active products"
            value={String(o.active_products)}
            className="border-ws-line bg-white text-ws-ink"
          />
          <Link to="/reports" className="block">
            <Card
              label="Low stock items"
              value={String(o.low_stock_items)}
              className="border-[#ffd8ba] bg-[#fff0e3] text-[#c95718]"
            />
          </Link>
        </div>
      )}
    </div>
  )
}

function Card({ label, value, className }: { label: string; value: string; className: string }) {
  return (
    <div className={`rounded-xl border p-4 ${className}`}>
      <div className="text-xs font-bold opacity-80">{label.toUpperCase()}</div>
      <div className="mt-2 text-2xl font-bold">{value}</div>
    </div>
  )
}
