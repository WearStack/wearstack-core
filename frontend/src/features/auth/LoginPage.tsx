import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { FormField } from '@/components/FormField'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Enter your password'),
})
type Values = z.infer<typeof schema>

export function LoginPage() {
  const { status, login } = useAuthStore()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const setup = useQuery({
    queryKey: ['setup-status'],
    queryFn: () => api<{ setup_required: boolean }>('/setup/status'),
  })
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  if (status === 'authed') return <Navigate to="/" replace />
  if (setup.data?.setup_required) return <Navigate to="/setup" replace />

  const onSubmit = async (v: Values) => {
    setError(null)
    try {
      await login(v.email, v.password)
      navigate('/', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed')
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm items-center p-4">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Sign in to Wearstack</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <FormField
              label="Email"
              type="email"
              autoComplete="username"
              error={errors.email?.message}
              {...register('email')}
            />
            <FormField
              label="Password"
              type="password"
              autoComplete="current-password"
              error={errors.password?.message}
              {...register('password')}
            />
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
          <p className="mt-4 text-center text-xs text-gray-500">
            <Link to="/setup">First time here?</Link>
          </p>
        </CardContent>
      </Card>
    </main>
  )
}
