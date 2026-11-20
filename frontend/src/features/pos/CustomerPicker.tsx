import { useQuery } from '@tanstack/react-query'
import { useDeferredValue, useState } from 'react'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Customer } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'
import { useCartStore } from '@/stores/cart'

export function CustomerPicker() {
  const canRead = useAuthStore((s) => s.can('customer:read'))
  const { customer, setCustomer } = useCartStore()
  const [q, setQ] = useState('')
  const deferred = useDeferredValue(q.trim())
  const results = useQuery({
    queryKey: ['customer-search', deferred],
    enabled: canRead && deferred.length >= 2,
    queryFn: () => api<Customer[]>(`/customers?q=${encodeURIComponent(deferred)}&limit=5`),
  })
  if (!canRead) return null

  if (customer) {
    return (
      <div className="flex items-center justify-between text-sm">
        <span>
          Customer: <b className="text-ws-ink">{customer.name}</b>
        </span>
        <button className="text-ws-blue underline" onClick={() => setCustomer(null)}>
          Remove
        </button>
      </div>
    )
  }
  return (
    <div className="space-y-1">
      <Input
        placeholder="Customer name or phone (optional)"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {deferred.length >= 2 && (
        <ul className="rounded-md border border-ws-line text-sm">
          {results.data?.map((c) => (
            <li key={c.id}>
              <button
                className="w-full px-3 py-2 text-left hover:bg-ws-bg"
                onClick={() => {
                  setCustomer({ id: c.id, name: c.name })
                  setQ('')
                }}
              >
                {c.name} {c.phone && <span className="text-ws-muted">· {c.phone}</span>}
              </button>
            </li>
          ))}
          {results.data?.length === 0 && (
            <li className="px-3 py-2 text-ws-muted">No customer found.</li>
          )}
        </ul>
      )}
    </div>
  )
}
