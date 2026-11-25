import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { useAuthStore } from '@/stores/auth'
import { AuthShell } from './AuthShell'

const MIN = 10
const schema = z
  .object({
    current: z.string().min(1, 'Enter your temporary password'),
    next: z
      .string()
      .min(MIN, `Use at least ${MIN} characters`)
      .max(128, 'Use at most 128 characters'),
    confirm: z.string(),
  })
  .refine((v) => v.next === v.confirm, { path: ['confirm'], message: 'The passwords do not match' })
  .refine((v) => v.next !== v.current, {
    path: ['next'],
    message: 'Choose a password different from the temporary one',
  })
type Values = z.infer<typeof schema>

const INPUT =
  'h-[46px] w-full rounded-[10px] border border-[#dce5f2] bg-[#f7f9fc] px-[13px] text-sm text-ws-ink ' +
  'placeholder:text-[#9aa7b8] focus:border-ws-blue focus:outline-2 focus:outline-ws-blue/25'
const LABEL = 'mt-4 mb-2 block text-xs font-bold text-[#1a355e]'

/** Shown to anyone whose password was set by an administrator, before they can use the app. */
export function ChangePasswordPage() {
  const { status, me, changePassword, logout } = useAuthStore()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  if (status === 'loading') return null
  if (status !== 'authed') return <Navigate to="/login" replace />
  if (!me?.must_change_password) return <Navigate to="/" replace />

  const onSubmit = async (v: Values) => {
    setError(null)
    try {
      await changePassword(v.current, v.next)
      navigate('/', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change the password')
    }
  }

  return (
    <AuthShell>
      <h2 className="mb-[9px] text-[30px] font-bold tracking-[-.8px] text-ws-ink">
        Choose your own password
      </h2>
      <p className="mb-6 text-sm text-[#77869b]">
        Hi {me.full_name.split(' ')[0]}. The password you were given is temporary. Choose one only
        you know before you start. Other devices you were signed in on will be signed out.
      </p>
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <label htmlFor="current" className={LABEL} style={{ marginTop: 0 }}>
          Temporary password
        </label>
        <input
          id="current"
          type="password"
          autoComplete="current-password"
          aria-invalid={!!errors.current}
          className={INPUT}
          {...register('current')}
        />
        {errors.current && <p className="mt-1 text-xs text-red-600">{errors.current.message}</p>}

        <label htmlFor="next" className={LABEL}>
          New password
        </label>
        <input
          id="next"
          type="password"
          autoComplete="new-password"
          placeholder={`At least ${MIN} characters`}
          aria-invalid={!!errors.next}
          className={INPUT}
          {...register('next')}
        />
        {errors.next && <p className="mt-1 text-xs text-red-600">{errors.next.message}</p>}

        <label htmlFor="confirm" className={LABEL}>
          Confirm new password
        </label>
        <input
          id="confirm"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.confirm}
          className={INPUT}
          {...register('confirm')}
        />
        {errors.confirm && <p className="mt-1 text-xs text-red-600">{errors.confirm.message}</p>}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-6 flex w-full items-center justify-between rounded-[10px] bg-ws-orange px-4 py-3.5 font-extrabold text-[#172d50] shadow-[0_5px_12px_#ff8a3230] hover:bg-[#ff9a50] disabled:opacity-60"
        >
          <span>{isSubmitting ? 'Saving…' : 'Set my password'}</span>
          <span aria-hidden>→</span>
        </button>
        {error && (
          <p role="alert" className="mt-3 rounded-lg bg-[#fff0e3] p-2.5 text-xs text-[#ad5817]">
            {error}
          </p>
        )}
      </form>
      <p className="mt-6 text-center text-[11px] text-[#9aa7b8]">
        Not you?{' '}
        <button
          className="text-ws-blue underline"
          onClick={async () => {
            await logout()
            navigate('/login', { replace: true })
          }}
        >
          Sign out
        </button>
      </p>
    </AuthShell>
  )
}
