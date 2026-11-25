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
import type { Role, Store, UserRow } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'
import { CredentialNotice } from './CredentialNotice'
import { fullDate, relativeTime } from './format'
import { generateTempPassword } from './tempPassword'
import { UserRowActions } from './UserRowActions'

function AddUser({
  roles,
  stores,
  viewerIsOwner,
}: {
  roles: Role[]
  stores: Store[]
  viewerIsOwner: boolean
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [roleId, setRoleId] = useState('')
  const [storeIds, setStoreIds] = useState<string[]>([])
  const [password, setPassword] = useState(() => generateTempPassword())
  const [created, setCreated] = useState<{ email: string; password: string; name: string } | null>(
    null,
  )
  const options = roles.filter((r) => viewerIsOwner || !(r.is_system && r.name === 'Owner'))

  const create = useMutation({
    mutationFn: () =>
      api<UserRow>('/users', 'POST', {
        full_name: name,
        email,
        password,
        role_id: roleId,
        store_ids: storeIds,
      }),
    onSuccess: (u) => {
      setCreated({ email: u.email, password, name: u.full_name })
      setName('')
      setEmail('')
      setRoleId('')
      setStoreIds([])
      setPassword(generateTempPassword())
      void qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
  })
  const field = (label: string, input: React.ReactNode) => (
    <label className="block space-y-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      {input}
    </label>
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-ws-ink">Add a person</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-ws-muted">
          There is no self-signup: accounts are created here. The person signs in with the temporary
          password below and must choose their own straight away.
        </p>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          {field(
            'Full name',
            <Input required value={name} onChange={(e) => setName(e.target.value)} />,
          )}
          {field(
            'Email',
            <Input
              required
              type="email"
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />,
          )}
          {field(
            'Role',
            <select
              required
              className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-sm"
              value={roleId}
              onChange={(e) => setRoleId(e.target.value)}
            >
              <option value="">Select…</option>
              {options.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>,
          )}
          {field(
            'Temporary password',
            <div className="flex gap-2">
              <Input
                required
                autoComplete="off"
                className="font-mono"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => setPassword(generateTempPassword())}
              >
                Generate
              </Button>
            </div>,
          )}
          <fieldset className="sm:col-span-2">
            <legend className="mb-1 text-sm font-medium">Stores they can work in</legend>
            <div className="flex flex-wrap gap-4">
              {stores.map((s) => (
                <label key={s.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={storeIds.includes(s.id)}
                    onChange={() =>
                      setStoreIds(
                        storeIds.includes(s.id)
                          ? storeIds.filter((x) => x !== s.id)
                          : [...storeIds, s.id],
                      )
                    }
                  />
                  {s.name}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="sm:col-span-2">
            {create.isError && (
              <p className="text-destructive mb-2 text-sm">{create.error.message}</p>
            )}
            <Button
              type="submit"
              disabled={create.isPending || !roleId || password.length < 10}
              className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
            >
              Create user
            </Button>
          </div>
        </form>
        {created && (
          <CredentialNotice
            heading={`${created.name} can now sign in`}
            email={created.email}
            password={created.password}
            onDone={() => setCreated(null)}
          />
        )}
      </CardContent>
    </Card>
  )
}

export function UsersPanel() {
  const can = useAuthStore((s) => s.can)
  const me = useAuthStore((s) => s.me)
  const canWrite = can('user:write')
  const users = useQuery({ queryKey: ['admin-users'], queryFn: () => api<UserRow[]>('/users') })
  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: () => api<Role[]>('/roles'),
    enabled: can('role:read'),
  })
  const stores = useQuery({
    queryKey: ['stores'],
    queryFn: () => api<Store[]>('/stores'),
    enabled: can('store:read'),
  })
  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? '—'
  const storeNames = (ids: string[]) =>
    ids
      .map((id) => stores.data?.find((s) => s.id === id)?.name)
      .filter(Boolean)
      .join(', ') || '—'
  const viewerIsOwner = me?.role === 'Owner'

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-ws-line bg-white p-2">
        <div className="flex justify-end pb-1">
          <Button
            size="sm"
            variant="outline"
            disabled={users.isFetching}
            onClick={() => void users.refetch()}
          >
            {users.isFetching ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Person</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last sign-in</TableHead>
              {canWrite && <TableHead className="text-right">Actions</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.data?.map((u) => (
              <TableRow key={u.id} className="align-top">
                <TableCell>
                  <div className="font-medium text-ws-ink">{u.full_name}</div>
                  <div className="text-xs text-ws-muted">{u.email}</div>
                  <div className="text-xs text-ws-muted">Stores: {storeNames(u.store_ids)}</div>
                </TableCell>
                <TableCell>{roleName(u.role_id)}</TableCell>
                <TableCell>
                  <span className={u.is_active ? 'text-green-700' : 'text-ws-muted'}>
                    {u.is_active ? 'Active' : 'Inactive'}
                  </span>
                  {u.must_change_password && (
                    <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                      Must choose a password
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <span title={u.last_login_at ? fullDate(u.last_login_at) : undefined}>
                    {relativeTime(u.last_login_at)}
                  </span>
                </TableCell>
                {canWrite && (
                  <TableCell className="min-w-[17rem] text-right">
                    <UserRowActions
                      user={u}
                      roles={roles.data ?? []}
                      stores={stores.data ?? []}
                      viewerIsOwner={viewerIsOwner}
                      canWrite={canWrite}
                    />
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {users.isError && <p className="text-destructive p-2 text-sm">Could not load users.</p>}
      </div>
      {canWrite && (
        <AddUser
          roles={roles.data ?? []}
          stores={stores.data ?? []}
          viewerIsOwner={viewerIsOwner}
        />
      )}
    </div>
  )
}
