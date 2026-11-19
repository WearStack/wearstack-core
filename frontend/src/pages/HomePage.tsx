import { useAuthStore } from '@/stores/auth'

export function HomePage() {
  const me = useAuthStore((s) => s.me)
  return (
    <div>
      <h1 className="text-xl font-semibold">Welcome, {me?.full_name}</h1>
      <p className="mt-2 text-sm text-gray-600">
        Catalogue, inventory and POS arrive in the next phases. For now, manage stores, users and
        roles from the menu.
      </p>
    </div>
  )
}
