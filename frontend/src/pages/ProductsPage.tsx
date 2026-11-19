import { useQuery } from '@tanstack/react-query'
import { Fragment, useEffect, useState } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { api, apiBlob } from '@/lib/api'
import { formatMoney } from '@/lib/format'
import type { NameItem, Product } from '@/lib/types'
import { useAuthStore } from '@/stores/auth'
import { CatalogueSetup } from './CatalogueSetup'
import { ProductForm } from './ProductForm'

/** The barcode endpoint needs the bearer token, so fetch it and show it from a blob URL. */
function BarcodeImage({ variantId }: { variantId: string }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    apiBlob(`/variants/${variantId}/barcode.svg`)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [variantId])
  return url ? <img src={url} alt="Barcode" className="h-14" /> : <span className="text-xs">…</span>
}

export function ProductsPage() {
  const canWrite = useAuthStore((s) => s.can('product:write'))
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const products = useQuery({
    queryKey: ['products', q],
    queryFn: () => api<Product[]>(`/products?limit=200${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  })
  const categories = useQuery({
    queryKey: ['categories'],
    queryFn: () => api<NameItem[]>('/categories'),
  })
  const categoryName = (id: string | null) => categories.data?.find((c) => c.id === id)?.name ?? '—'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ws-ink">Products</h1>
        <p className="text-sm text-ws-muted">Manage your product catalogue.</p>
      </div>
      <div className="rounded-xl border border-ws-line bg-white p-4">
        <Input
          className="mb-3 max-w-sm"
          placeholder="Search name, SKU or barcode…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Price</TableHead>
              <TableHead>Variants</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {products.data?.map((p) => (
              <Fragment key={p.id}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() => setOpen(open === p.id ? null : p.id)}
                >
                  <TableCell className="font-medium text-ws-ink">{p.name}</TableCell>
                  <TableCell>{categoryName(p.category_id)}</TableCell>
                  <TableCell>{formatMoney(p.selling_price)}</TableCell>
                  <TableCell>
                    <span className="rounded-full bg-[#fff0e3] px-2 py-0.5 text-xs font-bold text-[#a84e0d]">
                      {p.variants.length}
                    </span>
                  </TableCell>
                </TableRow>
                {open === p.id && (
                  <TableRow>
                    <TableCell colSpan={4} className="bg-ws-bg">
                      <div className="grid gap-3 sm:grid-cols-2">
                        {p.variants.map((v) => (
                          <div
                            key={v.id}
                            className="flex items-center justify-between gap-3 rounded-lg border border-ws-line bg-white p-3 text-xs"
                          >
                            <div>
                              <b className="text-sm text-ws-ink">
                                {[v.size, v.colour].filter(Boolean).join(' / ') || 'Default'}
                              </b>
                              <div>SKU {v.sku}</div>
                              <div>{v.barcode}</div>
                              <div>
                                {formatMoney(v.selling_price)}
                                {v.has_price_override && ' (override)'}
                              </div>
                            </div>
                            <BarcodeImage variantId={v.id} />
                          </div>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            ))}
          </TableBody>
        </Table>
        {products.data?.length === 0 && (
          <p className="py-6 text-center text-sm text-ws-muted">No products yet.</p>
        )}
        {products.isError && <p className="text-destructive text-sm">Could not load products.</p>}
      </div>
      {canWrite && <ProductForm />}
      <CatalogueSetup canWrite={canWrite} />
    </div>
  )
}
