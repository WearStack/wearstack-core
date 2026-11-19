import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { FormField } from '@/components/FormField'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

const schema = z.object({
  business_name: z.string().min(1, 'Required'),
  state_code: z.string().regex(/^\d{2}$/, '2-digit GST state code, e.g. 27'),
  gstin: z
    .string()
    .regex(/^\d{2}[A-Z0-9]{13}$/, 'Invalid GSTIN')
    .or(z.literal('')),
  store_name: z.string().min(1, 'Required'),
  store_code: z.string().min(1, 'Required').max(20),
  owner_name: z.string().min(1, 'Required'),
  owner_email: z.string().email('Enter a valid email'),
  owner_password: z.string().min(10, 'At least 10 characters'),
})
type Values = z.infer<typeof schema>

export function SetupPage() {
  const login = useAuthStore((s) => s.login)
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
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { gstin: '' } })

  if (setup.data && !setup.data.setup_required) return <Navigate to="/login" replace />

  const onSubmit = async (v: Values) => {
    setError(null)
    try {
      await api('/setup', 'POST', { ...v, gstin: v.gstin || null })
      await login(v.owner_email, v.owner_password)
      navigate('/', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Setup failed')
    }
  }

  return (
    <main className="mx-auto max-w-xl p-4">
      <Card>
        <CardHeader>
          <CardTitle>Set up your business</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2" noValidate>
            <FormField
              label="Business name"
              error={errors.business_name?.message}
              {...register('business_name')}
            />
            <FormField
              label="GST state code"
              placeholder="27"
              error={errors.state_code?.message}
              {...register('state_code')}
            />
            <FormField
              label="GSTIN (optional)"
              error={errors.gstin?.message}
              {...register('gstin')}
            />
            <div />
            <FormField
              label="First store name"
              error={errors.store_name?.message}
              {...register('store_name')}
            />
            <FormField
              label="Store code"
              placeholder="MAIN"
              error={errors.store_code?.message}
              {...register('store_code')}
            />
            <FormField
              label="Your name"
              error={errors.owner_name?.message}
              {...register('owner_name')}
            />
            <FormField
              label="Email"
              type="email"
              autoComplete="username"
              error={errors.owner_email?.message}
              {...register('owner_email')}
            />
            <FormField
              label="Password"
              type="password"
              autoComplete="new-password"
              error={errors.owner_password?.message}
              {...register('owner_password')}
            />
            <div className="sm:col-span-2">
              {error && <p className="text-destructive mb-2 text-sm">{error}</p>}
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? 'Creating…' : 'Create business'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
