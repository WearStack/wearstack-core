import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { FormField } from '@/components/FormField'
import { Button } from '@/components/ui/button'
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
import type { Store } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

const schema = z.object({
  code: z.string().min(1, 'Required').max(20),
  name: z.string().min(1, 'Required'),
  state_code: z.string().regex(/^\d{2}$/, '2-digit GST state code'),
})
type Values = z.infer<typeof schema>

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
    },
  })
  const toggle = useMutation({
    mutationFn: (s: Store) => api<Store>(`/stores/${s.id}`, 'PATCH', { is_active: !s.is_active }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['stores'] }),
  })

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Stores</h1>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Code</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>State</TableHead>
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
              className="grid gap-4 sm:grid-cols-4 sm:items-end"
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
