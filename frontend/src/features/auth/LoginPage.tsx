import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { AuthShell } from './AuthShell'

const schema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password'),
  remember: z.boolean(),
})
type Values = z.infer<typeof schema>

const INPUT =
  'h-[46px] w-full rounded-[10px] border border-[#dce5f2] bg-[#f7f9fc] px-[13px] text-sm text-ws-ink ' +
  'placeholder:text-[#9aa7b8] focus:border-ws-blue focus:outline-2 focus:outline-ws-blue/25'
const LABEL = 'mt-4 mb-2 block text-xs font-bold text-[#1a355e]'

// Development convenience only: the build for production drops this block entirely, so a
// deployed Wearstack never offers a shortcut around signing in.
const DEMO = import.meta.env.DEV
  ? { email: 'owner@yopmail.com', password: 'demo-password-123' }
  : null

export function LoginPage() {
  const { status, login } = useAuthStore()
  const navigate = useNavigate()
  const [notice, setNotice] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const setup = useQuery({
    queryKey: ['setup-status'],
    queryFn: () => api<{ setup_required: boolean }>('/setup/status'),
  })
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { remember: false } })

  if (status === 'authed') return <Navigate to="/" replace />
  if (setup.data?.setup_required) return <Navigate to="/setup" replace />

  const signIn = async (email: string, password: string, remember: boolean) => {
    setNotice(null)
    try {
      await login(email, password, remember)
      navigate('/', { replace: true })
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Sign in failed')
    }
  }

  return (
    <AuthShell>
      <h2 className="mb-[9px] text-[30px] font-bold tracking-[-.8px] text-ws-ink">Welcome back</h2>
      <p className="mb-7 text-sm text-[#77869b]">Sign in to your Wearstack workspace.</p>
      <form onSubmit={handleSubmit((v) => signIn(v.email, v.password, v.remember))} noValidate>
        <label htmlFor="email" className={LABEL} style={{ marginTop: 0 }}>
          Email address
        </label>
        <input
          id="email"
          type="email"
          placeholder="you@yourstore.com"
          autoComplete="username"
          aria-invalid={!!errors.email}
          className={INPUT}
          {...register('email')}
        />
        {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>}

        <label htmlFor="password" className={LABEL}>
          Password
        </label>
        <div className="relative">
          <input
            id="password"
            type={showPassword ? 'text' : 'password'}
            placeholder="Enter your password"
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            className={`${INPUT} pr-[70px]`}
            {...register('password')}
          />
          <button
            type="button"
            aria-pressed={showPassword}
            aria-controls="password"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute top-1/2 right-3 -translate-y-1/2 text-xs font-bold text-ws-blue"
          >
            {showPassword ? 'Hide' : 'Show'}
          </button>
        </div>
        {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>}

        <div className="mt-[15px] mb-[22px] flex items-center justify-between text-xs">
          <label className="flex items-center gap-[7px] text-[#64748b]">
            <input type="checkbox" {...register('remember')} />
            Remember me
          </label>
          <button
            type="button"
            className="font-bold text-ws-blue"
            onClick={() =>
              setNotice(
                'Password reset by email is not available yet. Ask your store owner or administrator to set a new password for you (Users → Reset password).',
              )
            }
          >
            Forgot password?
          </button>
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="flex w-full items-center justify-between rounded-[10px] bg-ws-orange px-4 py-3.5 font-extrabold text-[#172d50] shadow-[0_5px_12px_#ff8a3230] hover:bg-[#ff9a50] disabled:opacity-60"
        >
          <span>{isSubmitting ? 'Signing in…' : 'Sign in'}</span>
          <span aria-hidden>→</span>
        </button>
        {notice && (
          <p role="alert" className="mt-3 rounded-lg bg-[#fff0e3] p-2.5 text-xs text-[#ad5817]">
            {notice}
          </p>
        )}
      </form>

      {DEMO && (
        <>
          <div className="my-[22px] flex items-center gap-3 text-[11px] text-[#9aa7b8] before:h-px before:flex-1 before:bg-[#e7edf5] after:h-px after:flex-1 after:bg-[#e7edf5]">
            OR
          </div>
          <button
            type="button"
            onClick={() => signIn(DEMO.email, DEMO.password, true)}
            className="w-full rounded-[10px] border border-[#dce5f2] bg-white p-[13px] font-bold text-[#174f9e]"
          >
            Explore demo dashboard
          </button>
          <p className="mt-2 text-center text-[11px] text-[#9aa7b8]">
            Development only: signs in as the seeded demo owner.
          </p>
        </>
      )}

      <p className="mt-6 text-center text-[11px] text-[#9aa7b8]">
        Don't have access? Contact your store administrator.
        <br />
        <br />© Wearstack · Retail management made simpler
      </p>
    </AuthShell>
  )
}
