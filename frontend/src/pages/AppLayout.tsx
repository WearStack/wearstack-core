import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useActiveStore } from '@/lib/useActiveStore'
import { useOfflineReadiness } from '@/offline/boot'
import { useOfflineSummary } from '@/offline/hooks'
import { useAuthStore } from '@/stores/auth'
import { useCartStore } from '@/stores/cart'
import { useUiStore } from '@/stores/ui'

interface Item {
  to: string
  label: string
  glyph: string
  permission?: string
  end?: boolean
  soon?: boolean
}

// Groups and glyphs follow the approved prototype (docs/ui/wearstack_prototype.html).
const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: 'MAIN',
    items: [
      { to: '/', label: 'Overview', glyph: '▦', end: true },
      { to: '/pos', label: 'Point of Sale', glyph: '🛒', permission: 'sale:create' },
      { to: '/sync', label: 'Sync', glyph: '⇅', permission: 'sale:create' },
    ],
  },
  {
    title: 'CATALOGUE',
    items: [
      { to: '/products', label: 'Products', glyph: '♧', permission: 'product:read' },
      { to: '/inventory', label: 'Inventory', glyph: '▣', permission: 'inventory:read' },
      { to: '/purchases', label: 'Purchases', glyph: '🚚', permission: 'purchase:read' },
    ],
  },
  {
    title: 'RELATIONSHIPS',
    items: [
      { to: '/customers', label: 'Customers', glyph: '♙', permission: 'customer:read' },
      { to: '/returns', label: 'Returns', glyph: '↻', soon: true },
    ],
  },
  {
    title: 'INSIGHTS',
    items: [{ to: '/reports', label: 'Reports', glyph: '▥', permission: 'report:read' }],
  },
  {
    title: 'SETTINGS',
    items: [
      { to: '/stores', label: 'Stores', glyph: '⌂', permission: 'store:read' },
      { to: '/users', label: 'Users', glyph: '☺', permission: 'user:read' },
      { to: '/roles', label: 'Roles', glyph: '⚿', permission: 'role:read' },
    ],
  },
]

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')

function Sidebar() {
  const can = useAuthStore((s) => s.can)
  return (
    <aside className="sticky top-0 flex h-screen w-[65px] shrink-0 flex-col overflow-y-auto bg-ws-navy p-2 text-white sm:w-[220px] sm:px-3.5 sm:py-5">
      <NavLink
        to="/"
        className="flex items-center justify-center gap-2.5 pb-5 sm:justify-start sm:px-2 sm:pb-6"
      >
        <span aria-hidden className="rounded-[10px] bg-ws-orange p-2.5 text-xl sm:text-[22px]">
          👕
        </span>
        <span className="hidden sm:block">
          <b className="text-[21px]">
            wearstack<span className="text-[#ffb36f]">.</span>
          </b>
          <small className="block text-[9px] tracking-wide text-[#d5e5fa]">RETAIL MANAGEMENT</small>
        </span>
      </NavLink>
      <nav aria-label="Main">
        {GROUPS.map((g) => {
          const visible = g.items.filter((i) => i.soon || !i.permission || can(i.permission))
          if (visible.length === 0) return null
          return (
            <div key={g.title}>
              <div className="mx-2 mt-4 mb-1.5 hidden text-[10px] tracking-[1px] text-[#afc8ea] sm:block">
                {g.title}
              </div>
              {visible.map((i) =>
                i.soon ? (
                  <div
                    key={i.label}
                    aria-disabled="true"
                    title="Coming soon"
                    className="my-0.5 flex w-full cursor-not-allowed items-center justify-center gap-2 rounded-[9px] p-3 font-semibold text-white/45 sm:justify-start"
                  >
                    <span aria-hidden>{i.glyph}</span>
                    <span className="hidden sm:inline">{i.label}</span>
                    <span className="ml-auto hidden rounded-full bg-white/15 px-1.5 py-0.5 text-[9px] sm:inline">
                      Soon
                    </span>
                  </div>
                ) : (
                  <NavLink
                    key={i.to}
                    to={i.to}
                    end={i.end}
                    title={i.label}
                    className={({ isActive }) =>
                      `my-0.5 flex w-full items-center justify-center gap-2 rounded-[9px] p-3 font-semibold sm:justify-start ${
                        isActive ? 'bg-ws-orange text-[#172d50]' : 'hover:bg-[#205eaf]'
                      }`
                    }
                  >
                    <span aria-hidden>{i.glyph}</span>
                    <span className="hidden sm:inline">{i.label}</span>
                  </NavLink>
                ),
              )}
            </div>
          )
        })}
      </nav>
    </aside>
  )
}

/** Connection and unsent-sales indicator; opens the Sync status page. */
function ConnectionBadge({ storeId }: { storeId: string }) {
  const { online, pending, needsAttention } = useOfflineSummary(storeId)
  return (
    <Link
      to="/sync"
      aria-label="Sync status"
      className="flex items-center gap-1.5 rounded-full border border-ws-line px-2.5 py-1 text-xs font-semibold text-ws-ink"
    >
      <span
        aria-hidden
        className={`size-2 rounded-full ${online ? 'bg-green-500' : 'bg-amber-500'}`}
      />
      <span>{online ? 'Online' : 'Offline'}</span>
      {pending > 0 && (
        <span className="rounded-full bg-amber-100 px-1.5 text-amber-800">
          {pending} {online ? 'to send' : 'saved'}
        </span>
      )}
      {needsAttention > 0 && (
        <span className="rounded-full bg-red-100 px-1.5 text-red-700">
          {needsAttention} to review
        </span>
      )}
    </Link>
  )
}

function TopBar() {
  const { me, logout } = useAuthStore()
  const canSell = useAuthStore((s) => s.can('sale:create'))
  const { stores, store } = useActiveStore()
  const setActive = useUiStore((s) => s.setActiveStoreId)
  const clearCart = useCartStore((s) => s.clear)
  const navigate = useNavigate()
  return (
    <header className="flex h-[70px] items-center justify-between gap-3 border-b border-ws-line bg-white px-4 sm:px-7">
      <div className="min-w-0">
        <div className="flex items-center gap-2 font-bold text-ws-ink">
          <span aria-hidden>▣</span>
          {stores.length > 1 ? (
            <select
              aria-label="Store"
              className="max-w-[200px] cursor-pointer truncate bg-transparent font-bold outline-none"
              value={store?.id ?? ''}
              onChange={(e) => {
                clearCart() // a basket belongs to one store's stock and prices
                setActive(e.target.value)
              }}
            >
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          ) : (
            <span>{store?.name ?? '—'}</span>
          )}
        </div>
        {store && (
          <div className="mt-0.5 truncate text-[11px] text-ws-muted">
            {store.address ? `${store.address} · ` : ''}Store {store.code}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {canSell && store && <ConnectionBadge storeId={store.id} />}
        <div
          aria-hidden
          className="grid size-10 place-items-center rounded-full bg-ws-orange text-sm font-bold text-ws-ink"
        >
          {initials(me?.full_name ?? '')}
        </div>
        <div className="hidden text-right sm:block">
          <b className="text-ws-ink">{me?.full_name}</b>
          <div className="text-[11px] text-ws-muted">{me?.role}</div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            await logout()
            navigate('/login')
          }}
        >
          Sign out
        </Button>
      </div>
    </header>
  )
}

function UpdateNotice() {
  const applyUpdate = useUiStore((s) => s.applyUpdate)
  if (!applyUpdate) return null
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 bg-ws-blue px-4 py-2 text-sm text-white"
    >
      <span>A new version of Wearstack is ready. Finish the current sale first, then reload.</span>
      <button
        className="rounded-md bg-white px-3 py-1 font-semibold text-ws-ink"
        onClick={applyUpdate}
      >
        Reload now
      </button>
    </div>
  )
}

export function AppLayout() {
  useOfflineReadiness()
  return (
    <div className="flex min-h-screen bg-ws-bg">
      <Sidebar />
      <div className="min-w-0 flex-1">
        <UpdateNotice />
        <TopBar />
        <main className="mx-auto max-w-[1500px] p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
