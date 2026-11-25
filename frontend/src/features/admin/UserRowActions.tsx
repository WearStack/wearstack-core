import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Role, Store, UserRow } from '@/lib/types'
import { CredentialNotice } from './CredentialNotice'
import { generateTempPassword } from './tempPassword'

type Mode = 'idle' | 'edit' | 'reset' | 'signout'

interface Props {
  user: UserRow
  roles: Role[]
  stores: Store[]
  /** Only an Owner may give or change the Owner role (the server enforces it too). */
  viewerIsOwner: boolean
  canWrite: boolean
}

/** The actions for one person in the Users table. */
export function UserRowActions({ user, roles, stores, viewerIsOwner, canWrite }: Props) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<Mode>('idle')
  const [name, setName] = useState(user.full_name)
  const [roleId, setRoleId] = useState(user.role_id)
  const [storeIds, setStoreIds] = useState<string[]>(user.store_ids)
  const [password, setPassword] = useState('')
  const [issued, setIssued] = useState<{ heading: string; password: string } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = () => void qc.invalidateQueries({ queryKey: ['admin-users'] })
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<UserRow>(`/users/${user.id}`, 'PATCH', body),
    onSuccess: refresh,
  })
  const signOut = useMutation({
    mutationFn: () => api(`/users/${user.id}/sign-out`, 'POST'),
    onSuccess: () => {
      setMode('idle')
      setNotice('Signed out everywhere')
      refresh()
    },
  })
  const error = patch.error ?? signOut.error

  if (!canWrite) return null

  const roleOptions = roles.filter((r) => viewerIsOwner || !(r.is_system && r.name === 'Owner'))
  const toggleStore = (id: string) =>
    setStoreIds(storeIds.includes(id) ? storeIds.filter((s) => s !== id) : [...storeIds, id])

  if (mode === 'edit') {
    return (
      <form
        className="space-y-2 text-left"
        onSubmit={(e) => {
          e.preventDefault()
          patch.mutate(
            { full_name: name, role_id: roleId, store_ids: storeIds },
            { onSuccess: () => setMode('idle') },
          )
        }}
      >
        <Input
          aria-label={`Name of ${user.full_name}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          aria-label={`Role of ${user.full_name}`}
          className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-sm"
          value={roleId}
          onChange={(e) => setRoleId(e.target.value)}
        >
          {roleOptions.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
          {!roleOptions.some((r) => r.id === user.role_id) && (
            <option value={user.role_id}>{roles.find((r) => r.id === user.role_id)?.name}</option>
          )}
        </select>
        <fieldset className="flex flex-wrap gap-3 text-xs">
          <legend className="sr-only">Stores for {user.full_name}</legend>
          {stores.map((s) => (
            <label key={s.id} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={storeIds.includes(s.id)}
                onChange={() => toggleStore(s.id)}
              />
              {s.name}
            </label>
          ))}
        </fieldset>
        <div className="flex gap-2">
          <Button size="sm" type="submit" disabled={patch.isPending || !name.trim()}>
            Save changes
          </Button>
          <Button size="sm" type="button" variant="outline" onClick={() => setMode('idle')}>
            Cancel
          </Button>
        </div>
        {error && <p className="text-destructive text-xs">{error.message}</p>}
      </form>
    )
  }

  if (mode === 'reset') {
    return (
      <form
        className="space-y-2 text-left"
        onSubmit={(e) => {
          e.preventDefault()
          patch.mutate(
            { password },
            {
              onSuccess: () => {
                setIssued({ heading: `Password changed for ${user.full_name}`, password })
                setPassword('')
                setMode('idle')
              },
            },
          )
        }}
      >
        <div className="flex gap-2">
          <Input
            className="h-8 w-52 font-mono"
            autoComplete="off"
            aria-label={`New password for ${user.full_name}`}
            placeholder="Temporary password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button
            size="sm"
            type="button"
            variant="outline"
            onClick={() => setPassword(generateTempPassword())}
          >
            Generate
          </Button>
        </div>
        <div className="flex gap-2">
          <Button size="sm" type="submit" disabled={password.length < 10 || patch.isPending}>
            Set password
          </Button>
          <Button size="sm" type="button" variant="outline" onClick={() => setMode('idle')}>
            Cancel
          </Button>
        </div>
        <p className="text-xs text-ws-muted">
          They will have to choose their own at next sign-in, and are signed out now.
        </p>
        {error && <p className="text-destructive text-xs">{error.message}</p>}
      </form>
    )
  }

  if (mode === 'signout') {
    return (
      <div className="space-y-2 text-left text-xs">
        <p>
          Sign {user.full_name} out of every device now? They can sign in again with their password.
        </p>
        <div className="flex gap-2">
          <Button size="sm" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
            Yes, sign out everywhere
          </Button>
          <Button size="sm" variant="outline" onClick={() => setMode('idle')}>
            Cancel
          </Button>
        </div>
        {error && <p className="text-destructive">{error.message}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap justify-end gap-1.5">
        <Button
          size="sm"
          variant="outline"
          aria-label={`Edit ${user.full_name}`}
          onClick={() => setMode('edit')}
        >
          Edit
        </Button>
        <Button
          size="sm"
          variant="outline"
          aria-label={`Reset password for ${user.full_name}`}
          onClick={() => {
            setIssued(null)
            setNotice(null)
            setMode('reset')
          }}
        >
          Reset password
        </Button>
        <Button
          size="sm"
          variant="outline"
          aria-label={`Sign out ${user.full_name} everywhere`}
          onClick={() => {
            setNotice(null)
            setMode('signout')
          }}
        >
          Sign out everywhere
        </Button>
        <Button
          size="sm"
          variant="outline"
          aria-label={`${user.is_active ? 'Deactivate' : 'Activate'} ${user.full_name}`}
          disabled={patch.isPending}
          onClick={() => patch.mutate({ is_active: !user.is_active })}
        >
          {user.is_active ? 'Deactivate' : 'Activate'}
        </Button>
      </div>
      {notice && <p className="text-xs text-green-700">{notice}</p>}
      {issued && (
        <CredentialNotice
          heading={issued.heading}
          email={user.email}
          password={issued.password}
          onDone={() => setIssued(null)}
        />
      )}
      {error && <p className="text-destructive text-xs">{error.message}</p>}
    </div>
  )
}
