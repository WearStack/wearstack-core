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
import type { Role, Store, UserRow } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

const schema = z.object({
  full_name: z.string().min(1, 'Required'),
  email: z.string().email('Enter a valid email'),
  password: z.string().min(10, 'At least 10 characters'),
  role_id: z.string().min(1, 'Choose a role'),
  store_ids: z.array(z.string()),
})
type Values = z.infer<typeof schema>

export function UsersPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.can('user:write'))
  const canSeeRoles = useAuthStore((s) => s.can('role:read'))
  const canSeeStores = useAuthStore((s) => s.can('store:read'))
  const users = useQuery({ queryKey: ['users'], queryFn: () => api<UserRow[]>('/users') })
  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: () => api<Role[]>('/roles'),
    enabled: canSeeRoles,
  })
  const stores = useQuery({
    queryKey: ['stores'],
    queryFn: () => api<Store[]>('/stores'),
    enabled: canSeeStores,
  })
  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? '—'

  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { store_ids: [] } })
  const create = useMutation({
    mutationFn: (v: Values) => api<UserRow>('/users', 'POST', v),
    onSuccess: () => {
      form.reset({ store_ids: [] })
      void qc.invalidateQueries({ queryKey: ['users'] })
    },
  })
  const toggle = useMutation({
    mutationFn: (u: UserRow) =>
      api<UserRow>(`/users/${u.id}`, 'PATCH', { is_active: !u.is_active }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['users'] }),
  })

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Users</h1>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            {canWrite && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.data?.map((u) => (
            <TableRow key={u.id}>
              <TableCell>{u.full_name}</TableCell>
              <TableCell>{u.email}</TableCell>
              <TableCell>{roleName(u.role_id)}</TableCell>
              <TableCell>{u.is_active ? 'Active' : 'Inactive'}</TableCell>
              {canWrite && (
                <TableCell className="text-right">
                  <Button variant="outline" size="sm" onClick={() => toggle.mutate(u)}>
                    {u.is_active ? 'Deactivate' : 'Activate'}
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {toggle.isError && <p className="text-destructive text-sm">{toggle.error.message}</p>}

      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle>Add user</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={form.handleSubmit((v) => create.mutate(v))}
              className="grid gap-4 sm:grid-cols-2"
              noValidate
            >
              <FormField
                label="Full name"
                error={form.formState.errors.full_name?.message}
                {...form.register('full_name')}
              />
              <FormField
                label="Email"
                type="email"
                error={form.formState.errors.email?.message}
                {...form.register('email')}
              />
              <FormField
                label="Temporary password"
                type="password"
                autoComplete="new-password"
                error={form.formState.errors.password?.message}
                {...form.register('password')}
              />
              <div className="space-y-1.5">
                <label htmlFor="role_id" className="text-sm font-medium">
                  Role
                </label>
                <select
                  id="role_id"
                  className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-sm"
                  {...form.register('role_id')}
                >
                  <option value="">Select…</option>
                  {roles.data?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
                {form.formState.errors.role_id && (
                  <p className="text-destructive text-sm">
                    {form.formState.errors.role_id.message}
                  </p>
                )}
              </div>
              <fieldset className="sm:col-span-2">
                <legend className="mb-1 text-sm font-medium">Store access</legend>
                <div className="flex flex-wrap gap-4">
                  {stores.data?.map((s) => (
                    <label key={s.id} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" value={s.id} {...form.register('store_ids')} />
                      {s.name}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="sm:col-span-2">
                {create.isError && (
                  <p className="text-destructive mb-2 text-sm">{create.error.message}</p>
                )}
                <Button type="submit" disabled={create.isPending}>
                  Create user
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
