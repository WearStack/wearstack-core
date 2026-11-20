import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { FormField } from '@/components/FormField'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import type { Business, Store } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

/** The business GSTIN is what invoices carry for any store without a GSTIN of its own. */
function BusinessCard({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient()
  const business = useQuery({ queryKey: ['business'], queryFn: () => api<Business>('/business') })
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const save = useMutation({
    mutationFn: () => api<Business>('/business', 'PATCH', { gstin: value.trim() || null }),
    onSuccess: () => {
      setEditing(false)
      void qc.invalidateQueries({ queryKey: ['business'] })
      void qc.invalidateQueries({ queryKey: ['stores'] })
      void qc.invalidateQueries({ queryKey: ['my-stores'] })
    },
  })
  const b = business.data
  if (!b) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Business</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div>
          <b>{b.name}</b> · state code {b.state_code}
        </div>
        {editing ? (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate()
            }}
          >
            <Input
              className="w-56"
              aria-label="Business GSTIN"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="15-character GSTIN"
            />
            <Button size="sm" type="submit" disabled={save.isPending}>
              Save
            </Button>
            <Button size="sm" type="button" variant="outline" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            {save.isError && <span className="text-destructive text-xs">{save.error.message}</span>}
          </form>
        ) : (
          <div className="flex items-center gap-2">
            <span>
              Business GSTIN: {b.gstin ?? <span className="font-medium text-red-600">Not set</span>}
            </span>
            {canWrite && (
              <button
                className="text-ws-blue text-xs underline"
                aria-label={`${b.gstin ? 'Edit' : 'Add'} business GSTIN`}
                onClick={() => {
                  setValue(b.gstin ?? '')
                  setEditing(true)
                }}
              >
                {b.gstin ? 'Edit' : 'Add GSTIN'}
              </button>
            )}
          </div>
        )}
        <p className="text-xs text-ws-muted">
          A GST invoice must carry the seller's GSTIN, so billing is blocked for a store until it
          has one of its own or the business has one.
        </p>
      </CardContent>
    </Card>
  )
}

const schema = z.object({
  code: z.string().min(1, 'Required').max(20),
  name: z.string().min(1, 'Required'),
  state_code: z.string().regex(/^\d{2}$/, '2-digit GST state code'),
  gstin: z.string(),
})
type Values = z.infer<typeof schema>

/** Billing needs the seller's GSTIN, so a missing one is shown prominently and editable here. */
function GstinCell({ store, canWrite }: { store: Store; canWrite: boolean }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(store.gstin ?? '')
  const save = useMutation({
    mutationFn: () => api<Store>(`/stores/${store.id}`, 'PATCH', { gstin: value.trim() || null }),
    onSuccess: () => {
      setEditing(false)
      void qc.invalidateQueries({ queryKey: ['stores'] })
      void qc.invalidateQueries({ queryKey: ['my-stores'] })
    },
  })
  if (!editing) {
    return (
      <span className="flex items-center gap-2">
        {store.gstin ??
          (store.effective_gstin ? (
            <span className="text-ws-muted">Uses the business GSTIN ({store.effective_gstin})</span>
          ) : (
            <span className="font-medium text-red-600">Not set: billing is blocked</span>
          ))}
        {canWrite && (
          <button
            className="text-ws-blue text-xs underline"
            aria-label={`${store.gstin ? 'Edit' : 'Set'} GSTIN for ${store.name}`}
            onClick={() => setEditing(true)}
          >
            {store.gstin ? 'Edit' : store.effective_gstin ? 'Set own GSTIN' : 'Add GSTIN'}
          </button>
        )}
      </span>
    )
  }
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <Input
        className="h-8 w-44"
        aria-label={`GSTIN for ${store.name}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="15-character GSTIN"
      />
      <Button size="sm" type="submit" disabled={save.isPending}>
        Save
      </Button>
      {save.isError && <span className="text-destructive text-xs">{save.error.message}</span>}
    </form>
  )
}

export function StoresPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.can('store:write'))
  const stores = useQuery({ queryKey: ['stores'], queryFn: () => api<Store[]>('/stores') })
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const create = useMutation({
    mutationFn: (v: Values) => api<Store>('/stores', 'POST', v),
    onSuccess: () => {
      form.reset()
      void qc.invalidateQueries({ queryKey: ['stores'] })
      void qc.invalidateQueries({ queryKey: ['my-stores'] })
    },
  })
  const toggle = useMutation({
    mutationFn: (s: Store) => api<Store>(`/stores/${s.id}`, 'PATCH', { is_active: !s.is_active }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['stores'] })
      void qc.invalidateQueries({ queryKey: ['my-stores'] })
    },
  })

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Stores</h1>
      <BusinessCard canWrite={canWrite} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Code</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>State</TableHead>
            <TableHead>GSTIN</TableHead>
            <TableHead>Status</TableHead>
            {canWrite && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {stores.data?.map((s) => (
            <TableRow key={s.id}>
              <TableCell>{s.code}</TableCell>
              <TableCell>{s.name}</TableCell>
              <TableCell>{s.state_code}</TableCell>
              <TableCell>
                <GstinCell store={s} canWrite={canWrite} />
              </TableCell>
              <TableCell>{s.is_active ? 'Active' : 'Inactive'}</TableCell>
              {canWrite && (
                <TableCell className="text-right">
                  <Button variant="outline" size="sm" onClick={() => toggle.mutate(s)}>
                    {s.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {stores.isError && <p className="text-destructive text-sm">Could not load stores.</p>}
      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle>Add store</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={form.handleSubmit((v) => create.mutate(v))}
              className="grid gap-4 sm:grid-cols-5 sm:items-end"
              noValidate
            >
              <FormField
                label="Code"
                error={form.formState.errors.code?.message}
                {...form.register('code')}
              />
              <FormField
                label="Name"
                error={form.formState.errors.name?.message}
                {...form.register('name')}
              />
              <FormField
                label="GST state code"
                error={form.formState.errors.state_code?.message}
                {...form.register('state_code')}
              />
              <FormField
                label="GSTIN (optional)"
                error={form.formState.errors.gstin?.message}
                {...form.register('gstin')}
              />
              <Button type="submit" disabled={create.isPending}>
                Add
              </Button>
            </form>
            {create.isError && (
              <p className="text-destructive mt-2 text-sm">{create.error.message}</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
