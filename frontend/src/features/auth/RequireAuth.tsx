import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'

export function RequireAuth() {
  const status = useAuthStore((s) => s.status)
  if (status === 'loading') return <p className="p-8 text-sm text-gray-600">Loading…</p>
  return status === 'authed' ? <Outlet /> : <Navigate to="/login" replace />
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
