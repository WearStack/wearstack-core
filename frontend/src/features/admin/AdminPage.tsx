import { useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { ActivityPanel } from './ActivityPanel'
import { UsersPanel } from './UsersPanel'

type Tab = 'users' | 'activity'

/** The one place where people are added and given access. There is no self-signup. */
export function AdminPage() {
  const can = useAuthStore((s) => s.can)
  const [tab, setTab] = useState<Tab>('users')
  const tabs: { id: Tab; label: string; allowed: boolean }[] = [
    { id: 'users', label: 'Users', allowed: can('user:read') },
    { id: 'activity', label: 'Activity', allowed: can('audit:read') },
  ]
  const visible = tabs.filter((t) => t.allowed)
  const active = visible.find((t) => t.id === tab) ?? visible[0]

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-ws-ink">Admin</h1>
        <p className="text-sm text-ws-muted">
          Add people, set what they can do, and see what has been done. Roles and stores have their
          own pages in Settings.
        </p>
      </div>
      <div role="tablist" className="flex gap-1 border-b border-ws-line">
        {visible.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={active?.id === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${active?.id === t.id ? 'border-ws-orange text-ws-ink' : 'border-transparent text-ws-muted'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {active?.id === 'users' && <UsersPanel />}
      {active?.id === 'activity' && <ActivityPanel />}
    </div>
  )
}
