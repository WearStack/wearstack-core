import { useQuery } from '@tanstack/react-query'
import { Route, Routes } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { API_URL } from '@/lib/api'

function Home() {
  const { data, isError, isLoading, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await fetch(`${API_URL}/health`)).json() as Promise<{ status: string }>,
  })
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-semibold">Wearstack</h1>
      <p className="mt-2 text-sm text-gray-600">
        API: {isLoading ? 'checking…' : isError ? 'unreachable' : data?.status}
      </p>
      <Button className="mt-4" onClick={() => refetch()}>
        Recheck API
      </Button>
    </main>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
    </Routes>
  )
}
