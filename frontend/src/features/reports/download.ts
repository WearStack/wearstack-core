import { apiBlob } from '@/lib/api'

/** Fetches with the bearer token (a plain link could not) and saves the file. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const url = URL.createObjectURL(await apiBlob(path))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
