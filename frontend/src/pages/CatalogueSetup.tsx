import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { NameItem, TaxRate } from '@/lib/types'

function NameAdder({
  path,
  label,
  singular,
}: {
  path: 'categories' | 'brands'
  label: string
  singular: string
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const items = useQuery({ queryKey: [path], queryFn: () => api<NameItem[]>(`/${path}`) })
  const add = useMutation({
    mutationFn: () => api<NameItem>(`/${path}`, 'POST', { name }),
    onSuccess: () => {
      setName('')
      void qc.invalidateQueries({ queryKey: [path] })
    },
  })
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-ws-ink">{label}</h3>
      <p className="min-h-5 text-xs text-ws-muted">
        {items.data?.map((i) => i.name).join(', ') || 'None yet'}
      </p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) add.mutate()
        }}
      >
        <Input
          placeholder={`New ${singular}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button type="submit" size="sm" className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90">
          Add
        </Button>
      </form>
      {add.isError && <p className="text-destructive text-xs">{add.error.message}</p>}
    </div>
  )
}

function TaxRates() {
  const qc = useQueryClient()
  const rates = useQuery({ queryKey: ['tax-rates'], queryFn: () => api<TaxRate[]>('/tax-rates') })
  const [form, setForm] = useState({ name: '', rate: '', effective_from: '' })
  const add = useMutation({
    mutationFn: () => api<TaxRate>('/tax-rates', 'POST', form),
    onSuccess: () => {
      setForm({ name: '', rate: '', effective_from: '' })
      void qc.invalidateQueries({ queryKey: ['tax-rates'] })
    },
  })
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value })
  return (
    <div className="space-y-2 sm:col-span-2">
      <h3 className="text-sm font-medium text-ws-ink">GST rates</h3>
      <p className="text-xs text-ws-muted">
        Enter rates as configured for your business. When GST changes, add a new rate with the same
        name and a new start date; old invoices keep the rate they were issued under.
      </p>
      <ul className="text-xs text-ws-ink">
        {rates.data?.map((r) => (
          <li key={r.id}>
            {r.name}: {r.rate}% from {r.effective_from}
            {r.effective_to ? ` to ${r.effective_to}` : ''}
          </li>
        ))}
      </ul>
      <form
        className="grid gap-2 sm:grid-cols-4"
        onSubmit={(e) => {
          e.preventDefault()
          add.mutate()
        }}
      >
        <Input placeholder="Name, e.g. Apparel" value={form.name} onChange={set('name')} required />
        <Input
          placeholder="Rate %"
          inputMode="decimal"
          value={form.rate}
          onChange={set('rate')}
          required
        />
        <Input type="date" value={form.effective_from} onChange={set('effective_from')} required />
        <Button type="submit" size="sm" className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90">
          Add rate
        </Button>
      </form>
      {add.isError && <p className="text-destructive text-xs">{add.error.message}</p>}
    </div>
  )
}

export function CatalogueSetup({ canWrite }: { canWrite: boolean }) {
  if (!canWrite) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-ws-ink">Categories, brands & GST rates</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 sm:grid-cols-2">
        <NameAdder path="categories" label="Categories" singular="category" />
        <NameAdder path="brands" label="Brands" singular="brand" />
        <TaxRates />
      </CardContent>
    </Card>
  )
}
