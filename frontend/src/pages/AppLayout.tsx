import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/auth'

const NAV = [
  { to: '/stores', label: 'Stores', permission: 'store:read' },
  { to: '/users', label: 'Users', permission: 'user:read' },
  { to: '/roles', label: 'Roles', permission: 'role:read' },
]

export function AppLayout() {
  const { me, can, logout } = useAuthStore()
  const navigate = useNavigate()
  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-4 border-b px-4 py-3">
        <NavLink to="/" className="font-semibold">
          Wearstack
        </NavLink>
        <nav className="flex gap-3 text-sm">
          {NAV.filter((n) => can(n.permission)).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => (isActive ? 'font-medium underline' : 'text-gray-600')}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span className="text-gray-600">
            {me?.full_name} · {me?.role}
          </span>
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
      <main className="mx-auto max-w-5xl p-4">
        <Outlet />
      </main>
    </div>
  )
}
