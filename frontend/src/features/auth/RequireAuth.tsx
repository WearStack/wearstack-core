import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'

export function RequireAuth() {
  const status = useAuthStore((s) => s.status)
  const mustChange = useAuthStore((s) => s.me?.must_change_password)
  if (status === 'loading') return <p className="p-8 text-sm text-gray-600">Loading…</p>
  if (status !== 'authed') return <Navigate to="/login" replace />
  // A temporary password has to be replaced before anything else (the server enforces it too).
  return mustChange ? <Navigate to="/change-password" replace /> : <Outlet />
}

/** Renders children only if the user holds the permission; otherwise a clear message. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string
  children: React.ReactNode
}) {
  const allowed = useAuthStore((s) => s.can(permission))
  return allowed ? (
    children
  ) : (
    <p className="text-sm text-gray-600">You don't have access to this page.</p>
  )
}
