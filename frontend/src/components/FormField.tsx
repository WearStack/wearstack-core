import type { ComponentProps } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface Props extends ComponentProps<typeof Input> {
  label: string
  error?: string
}

export function FormField({ label, error, id, ...inputProps }: Props) {
  const fieldId = id ?? inputProps.name
  return (
    <div className="space-y-1.5">
      <Label htmlFor={fieldId}>{label}</Label>
      <Input id={fieldId} aria-invalid={!!error} {...inputProps} />
      {error && <p className="text-destructive text-sm">{error}</p>}
    </div>
  )
}
