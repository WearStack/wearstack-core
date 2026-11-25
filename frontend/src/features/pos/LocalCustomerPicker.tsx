import { useLiveQuery } from 'dexie-react-hooks'
import { useDeferredValue, useState } from 'react'
import { Input } from '@/components/ui/input'
import { db } from '@/offline/db'
import { useCartStore } from '@/stores/cart'

/** Customer search over the copy kept on this device. */
export function LocalCustomerPicker() {
  const { customer, setCustomer } = useCartStore()
  const [q, setQ] = useState('')
  const deferred = useDeferredValue(q.trim().toLowerCase())
  const results = useLiveQuery(
    () =>
      deferred.length < 2
        ? []
        : db.customers
            .filter(
              (c) => c.name.toLowerCase().includes(deferred) || (c.phone ?? '').includes(deferred),
            )
            .limit(5)
            .toArray(),
    [deferred],
    [],
  )
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
          {results.map((c) => (
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
          {results.length === 0 && <li className="px-3 py-2 text-ws-muted">No customer found.</li>}
        </ul>
      )}
    </div>
  )
}
