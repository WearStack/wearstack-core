import { fromPaise, toPaise } from '@/lib/money'

/**
 * The few billing rules an offline till must apply itself. They mirror the server's arithmetic
 * exactly (and are tested against shared/offline-vectors.json, generated from the server), because
 * the customer pays the total shown here and the server later issues the invoice for it.
 *
 * Prices are tax-inclusive, so the total does not depend on any GST rate: it is the sum of the
 * lines less discounts, rounded to the rupee (half up). The GST breakdown is produced by the
 * server when the sale syncs and the final invoice is issued.
 */
export interface BasketLine {
  unitPrice: string
  quantity: number
  discount: string
}

export interface Totals {
  subtotalPaise: number
  grandTotalPaise: number
  /** grand total minus subtotal: the rounding the customer sees on the receipt. */
  roundOffPaise: number
}

/** Rounds half up to a whole rupee, in paise. Totals are never negative. */
export const roundToRupeePaise = (paise: number): number => Math.floor((paise + 50) / 100) * 100

/** Largest discount a line may carry without the sale:discount permission, in paise. */
export const discountLimitPaise = (grossPaise: number, percent: number): number =>
  Math.floor((grossPaise * percent + 50) / 100)

export const lineGrossPaise = (l: BasketLine): number | null => {
  const unit = toPaise(l.unitPrice)
  return unit === null ? null : unit * l.quantity
}

/** Null if any amount is not a valid money value or a discount exceeds its line. */
export function computeTotals(lines: BasketLine[]): Totals | null {
  let subtotal = 0
  for (const l of lines) {
    const gross = lineGrossPaise(l)
    const discount = toPaise(l.discount)
    if (gross === null || discount === null || discount > gross) return null
    subtotal += gross - discount
  }
  const grand = roundToRupeePaise(subtotal)
  return { subtotalPaise: subtotal, grandTotalPaise: grand, roundOffPaise: grand - subtotal }
}

/** An explanation if the basket breaks a billing rule, else null. */
export function discountProblem(
  lines: BasketLine[],
  freePercent: number,
  mayDiscount: boolean,
): string | null {
  for (const l of lines) {
    const gross = lineGrossPaise(l)
    const discount = toPaise(l.discount)
    if (gross === null || discount === null) return 'Enter discounts as amounts like 50 or 49.50.'
    if (discount > gross) return 'A discount cannot be more than the item price.'
    if (discount > discountLimitPaise(gross, freePercent) && !mayDiscount) {
      return `Discounts above ${freePercent}% need a manager's permission.`
    }
  }
  return null
}

export const formatTotal = (paise: number): string => fromPaise(paise)
