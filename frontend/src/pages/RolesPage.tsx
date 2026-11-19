import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Role } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'

function PermissionPicker({
  catalogue,
  value,
  onChange,
  disabled,
}: {
  catalogue: Record<string, string>
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  const toggle = (code: string) =>
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  return (
    <div className="grid gap-1 sm:grid-cols-2">
      {Object.entries(catalogue).map(([code, description]) => (
        <label key={code} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value.includes(code)}
            disabled={disabled}
            onChange={() => toggle(code)}
          />
          <span>
            {description} <code className="text-xs text-gray-500">{code}</code>
          </span>
        </label>
      ))}
    </div>
  )
}

function RoleCard({
  role,
  catalogue,
  canWrite,
}: {
  role: Role
  catalogue: Record<string, string>
  canWrite: boolean
}) {
  const qc = useQueryClient()
  const [perms, setPerms] = useState(role.permissions)
  const editable = canWrite && !role.is_system
  const save = useMutation({
    mutationFn: () => api<Role>(`/roles/${role.id}`, 'PATCH', { permissions: perms }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['roles'] }),
  })
  const remove = useMutation({
    mutationFn: () => api(`/roles/${role.id}`, 'DELETE'),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['roles'] }),
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {role.name}{' '}
          {role.is_system && <span className="text-xs font-normal text-gray-500">(built-in)</span>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <PermissionPicker
          catalogue={catalogue}
          value={perms}
          onChange={setPerms}
          disabled={!editable}
        />
        {editable && (
          <div className="flex gap-2">
            <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
              Save
            </Button>
            <Button size="sm" variant="outline" onClick={() => remove.mutate()}>
              Delete
            </Button>
          </div>
        )}
        {(save.isError || remove.isError) && (
          <p className="text-destructive text-sm">{(save.error ?? remove.error)?.message}</p>
        )}
      </CardContent>
    </Card>
  )
}

export function RolesPage() {
  const qc = useQueryClient()
  const canWrite = useAuthStore((s) => s.can('role:write'))
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => api<Role[]>('/roles') })
  const catalogue = useQuery({
    queryKey: ['permissions'],
    queryFn: () => api<Record<string, string>>('/permissions'),
  })
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: () => api<Role>('/roles', 'POST', { name, permissions: [] }),
    onSuccess: () => {
      setName('')
      void qc.invalidateQueries({ queryKey: ['roles'] })
    },
  })

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Roles</h1>
      {canWrite && (
        <form
          className="flex max-w-sm gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate()
          }}
        >
          <Input
            placeholder="New role name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" disabled={create.isPending}>
            Add
          </Button>
        </form>
      )}
      {create.isError && <p className="text-destructive text-sm">{create.error.message}</p>}
      {catalogue.data &&
        roles.data?.map((r) => (
          <RoleCard
            key={r.id + r.permissions.join()}
            role={r}
            catalogue={catalogue.data}
            canWrite={canWrite}
          />
        ))}
    </div>
  )
}
