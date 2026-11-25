import { useInfiniteQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { api } from '@/lib/api'
import type { AuditRow } from '@/lib/types'
import { describeAudit, KINDS } from './describeAudit'
import { fullDate } from './format'

const PAGE = 50

/** Who did what, newest first: a readable view of the audit trail. */
export function ActivityPanel() {
  const [kind, setKind] = useState('all')
  const prefix = KINDS.find((k) => k.id === kind)?.prefix ?? ''
  const log = useInfiniteQuery({
    queryKey: ['audit', kind],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<AuditRow[]>(
        `/audit-logs?limit=${PAGE}&offset=${pageParam}${prefix ? `&action_prefix=${encodeURIComponent(prefix)}` : ''}`,
      ),
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
  })
  const rows = log.data?.pages.flat() ?? []

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-ws-muted">Show</span>
        <select
          className="border-input h-9 rounded-md border bg-white px-2 text-sm"
          aria-label="Kind of activity"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          {KINDS.map((k) => (
            <option key={k.id} value={k.id}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <div className="rounded-xl border border-ws-line bg-white p-2">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Who</TableHead>
              <TableHead>What</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="text-xs whitespace-nowrap">
                  {fullDate(a.created_at)}
                </TableCell>
                <TableCell>{a.user_name ?? 'System'}</TableCell>
                <TableCell>{describeAudit(a)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {log.isSuccess && rows.length === 0 && (
          <p className="py-6 text-center text-sm text-ws-muted">Nothing recorded yet.</p>
        )}
        {log.isError && <p className="text-destructive p-2 text-sm">{log.error.message}</p>}
      </div>
      {log.hasNextPage && (
        <Button
          variant="outline"
          size="sm"
          disabled={log.isFetchingNextPage}
          onClick={() => log.fetchNextPage()}
        >
          {log.isFetchingNextPage ? 'Loading…' : 'Show more'}
        </Button>
      )}
    </div>
  )
}
