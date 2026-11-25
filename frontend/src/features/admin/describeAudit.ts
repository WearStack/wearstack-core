import type { AuditRow } from '@/lib/types'

/** "supplier.created" -> "Supplier created": the fallback for any action not listed below. */
const readable = (code: string) => {
  const words = code.replace(/[._]/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const text = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v))

/** One readable line for an audit entry. Unknown actions fall back to the raw code. */
export function describeAudit(a: AuditRow): string {
  const after = a.after ?? {}
  const before = a.before ?? {}
  switch (a.action) {
    case 'setup.completed':
      return 'Set up the business'
    case 'user.created':
      return `Added ${text(after.email)}`
    case 'user.updated':
      if (after.password_changed) return `Reset the password of ${text(after.email)}`
      if (before.is_active !== after.is_active)
        return `${after.is_active ? 'Reactivated' : 'Deactivated'} ${text(after.email)}`
      return `Changed the details or access of ${text(after.email)}`
    case 'user.signed_out':
      return `Signed ${text(after.email)} out everywhere`
    case 'user.password_changed':
      return 'Changed their own password'
    case 'store.created':
      return `Added the store ${text(after.name)}`
    case 'store.updated':
      return `Changed the store ${text(after.name)}`
    case 'business.updated':
      return 'Changed the business details'
    case 'role.created':
      return `Added the role ${text(after.name)}`
    case 'role.updated':
      return `Changed the role ${text(after.name)}`
    case 'role.deleted':
      return `Deleted the role ${text(before.name)}`
    case 'sale.created':
      return `Sale ${text(after.invoice)} for ₹${text(after.total)}`
    case 'stock.opening':
    case 'stock.adjustment':
      return `Stock ${a.action === 'stock.opening' ? 'opening balance' : 'adjustment'} of ${text(after.delta)}${after.reason ? ` (${text(after.reason)})` : ''}`
    case 'purchase.received':
      return `Received purchase bill ${text(after.bill)}`
    case 'sync.accept':
      return 'Accepted an offline sale'
    case 'sync.reject':
      return 'Rejected an offline sale'
    case 'sync.conflict':
      return 'An offline sale needs a manager to review it'
    case 'sync.failed':
      return 'An offline sale could not be applied'
    case 'sync.retry':
      return 'Tried an offline sale again'
    case 'purchase.created':
      return `Entered purchase bill ${text(after.bill)}`
    case 'purchase.deleted':
      return `Deleted draft purchase bill ${text(before.bill)}`
    case 'supplier.created':
      return `Added the supplier ${text(after.name)}`
    case 'customer.created':
      return `Added the customer ${text(after.name)}`
    case 'customer.updated':
      return 'Changed a customer'
    case 'product.created':
      return `Added the product ${text(after.name)}`
    case 'product.updated':
      return 'Changed a product'
    case 'variant.created':
      return `Added the variant ${text(after.sku)}`
    case 'variant.updated':
      return 'Changed a product variant'
    case 'product.image_added':
      return 'Added a product photo'
    case 'product.image_removed':
      return 'Removed a product photo'
    case 'tax_rate.created':
      return 'Added a GST rate'
    case 'tax_rate.ended':
      return 'Ended a GST rate'
    default:
      return readable(a.action)
  }
}

export const KINDS: { id: string; label: string; prefix: string }[] = [
  { id: 'all', label: 'Everything', prefix: '' },
  { id: 'people', label: 'People and access', prefix: 'user.' },
  { id: 'roles', label: 'Roles', prefix: 'role.' },
  { id: 'stores', label: 'Stores and business', prefix: 'store.' },
  { id: 'sales', label: 'Sales', prefix: 'sale.' },
  { id: 'stock', label: 'Stock', prefix: 'stock.' },
  { id: 'sync', label: 'Offline sync', prefix: 'sync.' },
]
