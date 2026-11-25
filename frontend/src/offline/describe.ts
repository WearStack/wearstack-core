import { formatMoney } from '@/lib/format'

type Conflict = Record<string, unknown>

/** Plain-language reasons for a held sale, for the cashier and for the manager reviewing it. */
export function describeConflict(c: Conflict): string {
  const name = String(c.product_name ?? 'An item')
  const label = c.variant_label ? ` (${String(c.variant_label)})` : ''
  switch (c.code) {
    case 'insufficient_stock':
      return `Not enough stock: ${name}${label}. ${String(c.requested)} sold, but the system had ${String(c.available)}.`
    case 'price_changed':
      return `Price changed: ${name}${label} was charged ${formatMoney(String(c.charged))}, the price is now ${formatMoney(String(c.current))}.`
    case 'product_inactive':
      return `${name}${label} has been deactivated since the sale.`
    case 'sale_too_old':
      return `This sale is more than ${String(c.max_days)} days old.`
    default:
      return String(c.code ?? 'Needs review')
  }
}

export const STATUS_LABEL: Record<string, string> = {
  pending: 'Waiting to send',
  syncing: 'Sending…',
  received: 'Being processed',
  applied: 'Synced',
  conflict: 'Needs a manager',
  failed: 'Could not be applied',
  rejected: 'Rejected',
}

export const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  syncing: 'bg-blue-100 text-blue-800',
  received: 'bg-blue-100 text-blue-800',
  applied: 'bg-green-100 text-green-800',
  conflict: 'bg-[#fff0e3] text-[#a84e0d]',
  failed: 'bg-red-100 text-red-700',
  rejected: 'bg-gray-200 text-gray-700',
}
