import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { parseList } from '@/lib/format'
import type { NameItem, Product, TaxRate } from '@/lib/types'

const EMPTY = {
  name: '',
  category_id: '',
  brand_id: '',
  hsn_code: '',
  tax_rate_id: '',
  selling_price: '',
  cost_price: '',
  sizes: '',
  colours: '',
}

const SELECT = 'border-input h-9 w-full rounded-md border bg-transparent px-2 text-sm'

export function ProductForm() {
  const qc = useQueryClient()
  const [f, setF] = useState(EMPTY)
  const categories = useQuery({
    queryKey: ['categories'],
    queryFn: () => api<NameItem[]>('/categories'),
  })
  const brands = useQuery({ queryKey: ['brands'], queryFn: () => api<NameItem[]>('/brands') })
  const rates = useQuery({ queryKey: ['tax-rates'], queryFn: () => api<TaxRate[]>('/tax-rates') })

  const sizes = parseList(f.sizes)
  const colours = parseList(f.colours)
  // Every size × colour pair becomes a variant; an empty list means "no size" / "no colour".
  const variants = (sizes.length ? sizes : ['']).flatMap((size) =>
    (colours.length ? colours : ['']).map((colour) => ({ size, colour })),
  )

  const create = useMutation({
    mutationFn: () =>
      api<Product>('/products', 'POST', {
        name: f.name,
        category_id: f.category_id || null,
        brand_id: f.brand_id || null,
        hsn_code: f.hsn_code || null,
        tax_rate_id: f.tax_rate_id || null,
        selling_price: f.selling_price,
        cost_price: f.cost_price || '0',
        variants,
      }),
    onSuccess: () => {
      setF(EMPTY)
      void qc.invalidateQueries({ queryKey: ['products'] })
    },
  })
  const set =
    (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setF({ ...f, [k]: e.target.value })

  // Wrapping the control in <label> links the two without needing generated ids.
  const field = (label: string, input: React.ReactNode) => (
    <label className="block space-y-1.5">
      <span className="text-sm leading-none font-medium">{label}</span>
      {input}
    </label>
  )
  // Rates share a name across date ranges; offer each class once, newest first.
  const rateOptions = [...new Map((rates.data ?? []).toReversed().map((r) => [r.name, r])).values()]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-ws-ink">Add product</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 sm:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate()
          }}
        >
          {field('Name', <Input value={f.name} onChange={set('name')} required />)}
          {field(
            'Category',
            <select className={SELECT} value={f.category_id} onChange={set('category_id')}>
              <option value="">None</option>
              {categories.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>,
          )}
          {field(
            'Brand',
            <select className={SELECT} value={f.brand_id} onChange={set('brand_id')}>
              <option value="">None</option>
              {brands.data?.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>,
          )}
          {field(
            'Selling price (₹)',
            <Input
              inputMode="decimal"
              value={f.selling_price}
              onChange={set('selling_price')}
              required
            />,
          )}
          {field(
            'Cost price (₹)',
            <Input inputMode="decimal" value={f.cost_price} onChange={set('cost_price')} />,
          )}
          {field(
            'HSN code',
            <Input
              inputMode="numeric"
              placeholder="4–8 digits"
              value={f.hsn_code}
              onChange={set('hsn_code')}
            />,
          )}
          {field(
            'GST rate',
            <select className={SELECT} value={f.tax_rate_id} onChange={set('tax_rate_id')}>
              <option value="">Not set</option>
              {rateOptions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.rate}%)
                </option>
              ))}
            </select>,
          )}
          {field(
            'Sizes (comma separated)',
            <Input placeholder="S, M, L, XL" value={f.sizes} onChange={set('sizes')} />,
          )}
          {field(
            'Colours (comma separated)',
            <Input placeholder="Blue, White" value={f.colours} onChange={set('colours')} />,
          )}
          <div className="flex items-center justify-between gap-3 sm:col-span-3">
            <p className="text-sm text-ws-muted">
              Creates <b className="text-ws-ink">{variants.length}</b> variant
              {variants.length === 1 ? '' : 's'}, each with its own SKU and barcode.
            </p>
            <Button
              type="submit"
              disabled={create.isPending}
              className="bg-ws-orange text-ws-ink hover:bg-ws-orange/90"
            >
              {create.isPending ? 'Saving…' : 'Create product'}
            </Button>
          </div>
          {create.isError && (
            <p className="text-destructive text-sm sm:col-span-3">{create.error.message}</p>
          )}
        </form>
      </CardContent>
    </Card>
  )
}
