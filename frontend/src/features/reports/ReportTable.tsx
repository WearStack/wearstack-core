import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatMoney } from '@/lib/format'
import type { ReportColumn, ReportData } from '@/lib/types'

const count = new Intl.NumberFormat('en-IN')

function show(value: string | number | undefined, kind: ReportColumn['kind']): string {
  if (value === undefined || value === '') return ''
  if (kind === 'money') return formatMoney(value)
  if (kind === 'int') return count.format(Number(value))
  if (kind === 'percent') return `${value}%`
  return String(value)
}

export function ReportTable({ report }: { report: ReportData }) {
  const numeric = (c: ReportColumn) => c.kind !== 'text'
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {report.columns.map((c) => (
            <TableHead key={c.key} className={numeric(c) ? 'text-right' : ''}>
              {c.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {report.rows.map((row, i) => (
          <TableRow key={i}>
            {report.columns.map((c) => (
              <TableCell key={c.key} className={numeric(c) ? 'text-right tabular-nums' : ''}>
                {show(row[c.key], c.kind)}
              </TableCell>
            ))}
          </TableRow>
        ))}
        {report.totals && (
          <TableRow className="bg-ws-bg font-semibold">
            {report.columns.map((c) => (
              <TableCell key={c.key} className={numeric(c) ? 'text-right tabular-nums' : ''}>
                {show(report.totals?.[c.key], c.kind)}
              </TableCell>
            ))}
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
