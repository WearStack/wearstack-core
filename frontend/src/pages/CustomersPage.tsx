import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import type { Customer } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

const EMPTY = {
  name: '',
  phone: '',
  email: '',
  gstin: '',
  state_code: '',
  marketing_consent: false,
}

export function CustomersPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.can('customer:write'))
  const [q, setQ] = useState('')
  const [f, setF] = useState(EMPTY)
  const customers = useQuery({
    queryKey: ['customers', q],
    queryFn: () => api<Customer[]>(`/customers?limit=200${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  })
  const create = useMutation({
    mutationFn: () =>
      api<Customer>('/customers', 'POST', {
        name: f.name,
        phone: f.phone || null,
        email: f.email || null,
        gstin: f.gstin || null,
        state_code: f.state_code || null,
        marketing_consent: f.marketing_consent,
      }),
    onSuccess: () => {
      setF(EMPTY)
      void qc.invalidateQueries({ queryKey: ['customers'] })
    },
  })
  const text = (k: 'name' | 'phone' | 'email' | 'gstin' | 'state_code') => ({
    value: f[k],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value }),
  })
  const field = (label: string, input: React.ReactNode) => (
    <label className="block space-y-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      {input}
    </label>
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ws-ink">Customers</h1>
        <p className="text-sm text-ws-muted">
          Customer profiles for billing and, later, purchase history.
        </p>
      </div>
      <div className="rounded-xl border border-ws-line bg-white p-4">
        <Input
          className="mb-3 max-w-sm"
          placeholder="Search name or phone…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Phone</TableHead>
              <TableHead>GSTIN</TableHead>
              <TableHead>Offers</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {customers.data?.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium text-ws-ink">{c.name}</TableCell>
                <TableCell>{c.phone ?? '—'}</TableCell>
                <TableCell>{c.gstin ?? '—'}</TableCell>
                <TableCell>{c.marketing_consent ? 'Opted in' : 'No'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {customers.data?.length === 0 && (
          <p className="py-6 text-center text-sm text-ws-muted">No customers yet.</p>
        )}
      </div>
      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle className="text-ws-ink">Add customer</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-4 sm:grid-cols-3"
              onSubmit={(e) => {
                e.preventDefault()
                create.mutate()
              }}
            >
              {field('Name', <Input required {...text('name')} />)}
              {field(
                'Phone',
                <Input inputMode="tel" placeholder="9876543210" {...text('phone')} />,
              )}
              {field('Email', <Input type="email" {...text('email')} />)}
              {field('GSTIN (for B2B invoices)', <Input {...text('gstin')} />)}
              {field('State code', <Input placeholder="27" {...text('state_code')} />)}
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <input
                  type="checkbox"
                  checked={f.marketing_consent}
                  onChange={(e) => setF({ ...f, marketing_consent: e.target.checked })}
                />
                Agreed to receive offers and updates
              </label>
              <div className="sm:col-span-3">
                {create.isError && (
                  <p className="text-destructive mb-2 text-sm">{create.error.message}</p>
                )}
                <Button
                  type="submit"
                  disabled={create.isPending}
                  className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
                >
                  Add customer
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
