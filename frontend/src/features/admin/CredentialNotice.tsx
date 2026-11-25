import { useState } from 'react'
import { Button } from '@/components/ui/button'

/** Shows a temporary password exactly once, after it is set, with a copy button. */
export function CredentialNotice({
  heading,
  email,
  password,
  onDone,
}: {
  heading: string
  email: string
  password: string
  onDone: () => void
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${email}\n${password}`)
      setCopied(true)
    } catch {
      /* no clipboard access (e.g. an insecure origin): the password is on screen to copy by hand */
    }
  }
  return (
    <div
      role="status"
      className="space-y-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm"
    >
      <b className="text-green-900">{heading}</b>
      <div className="font-mono text-green-900">
        {email}
        <br />
        <span data-testid="temp-password">{password}</span>
      </div>
      <p className="text-xs text-green-900">
        Share this securely. It is shown only now, and the person must choose their own password
        when they first sign in.
      </p>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
        <Button size="sm" variant="outline" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  )
}
