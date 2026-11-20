import { toPaise } from '@/lib/money'

export type Method = 'cash' | 'upi' | 'card'
export interface PaymentRow {
  id: string
  method: Method
  amount: string
  reference: string
}

export const paymentsPaise = (rows: PaymentRow[]) =>
  rows.reduce<number | null>((sum, r) => {
    const p = toPaise(r.amount)
    return sum === null || p === null ? null : sum + p
  }, 0)

export const paymentsReady = (rows: PaymentRow[], totalPaise: number) =>
  rows.length > 0 &&
  paymentsPaise(rows) === totalPaise &&
  rows.every(
    (r) => (toPaise(r.amount) ?? 0) > 0 && (r.method === 'cash' || r.reference.trim() !== ''),
  )
