import { formatMoney } from '@/lib/format'

interface Props {
  labels: string[]
  values: number[]
  title: string
}

/** Up to five evenly spaced labels, first and last included. */
function ticks(labels: string[]): string[] {
  if (labels.length <= 5) return labels
  const n = 5
  return Array.from(
    { length: n },
    (_, i) => labels[Math.round((i * (labels.length - 1)) / (n - 1))],
  )
}

/** Simple bars in the brand colours; each bar carries its exact value for hover and screen readers. */
export function BarChart({ labels, values, title }: Props) {
  const max = Math.max(...values, 1)
  return (
    <figure aria-label={title} className="rounded-xl border border-ws-line bg-white p-4">
      <figcaption className="mb-3 text-sm font-semibold text-ws-ink">{title}</figcaption>
      <div className="flex h-40 items-end gap-1 border-b border-ws-line">
        {values.map((v, i) => (
          <div
            key={labels[i]}
            title={`${labels[i]}: ${formatMoney(v)}`}
            aria-label={`${labels[i]}: ${formatMoney(v)}`}
            className={`min-w-1 flex-1 rounded-t ${i % 3 === 0 ? 'bg-ws-blue' : 'bg-ws-orange'}`}
            style={{ height: `${Math.max((v / max) * 100, v > 0 ? 2 : 0)}%` }}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ws-muted">
        {ticks(labels).map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </figure>
  )
}
