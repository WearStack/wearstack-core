import { describe, expect, it } from 'vitest'
import vectors from './offline-vectors.json'
import { fromPaise } from '@/lib/money'
import { computeTotals, discountLimitPaise, discountProblem, roundToRupeePaise } from './rules'

describe('offline totals match the server (shared vectors)', () => {
  for (const [i, c] of vectors.totals.entries()) {
    it(`case ${i}: ${c.lines.map((l) => `${l.quantity}x${l.unit_price}-${l.discount}`).join(' + ')}`, () => {
      const t = computeTotals(
        c.lines.map((l) => ({
          unitPrice: l.unit_price,
          quantity: l.quantity,
          discount: l.discount,
        })),
      )
      expect(t).not.toBeNull()
      expect(fromPaise(t!.subtotalPaise)).toBe(c.subtotal)
      expect(fromPaise(t!.grandTotalPaise)).toBe(c.grand_total)
      expect(fromPaise(t!.roundOffPaise)).toBe(c.round_off)
    })
  }
})

describe('free-discount limit matches the server (shared vectors)', () => {
  for (const c of vectors.discount_limits) {
    it(`${c.percent}% of ${c.gross} is ${c.limit}`, () => {
      const gross = Math.round(Number(c.gross) * 100)
      expect(fromPaise(discountLimitPaise(gross, c.percent))).toBe(c.limit)
    })
  }
})

describe('rounding and validation', () => {
  it('rounds half up to the rupee', () => {
    expect(roundToRupeePaise(99950)).toBe(100000)
    expect(roundToRupeePaise(99949)).toBe(99900)
    expect(roundToRupeePaise(0)).toBe(0)
    expect(roundToRupeePaise(50)).toBe(100)
    expect(roundToRupeePaise(49)).toBe(0)
  })

  it('rejects malformed money and over-large discounts instead of guessing', () => {
    expect(computeTotals([{ unitPrice: '12.345', quantity: 1, discount: '0' }])).toBeNull()
    expect(computeTotals([{ unitPrice: 'abc', quantity: 1, discount: '0' }])).toBeNull()
    expect(computeTotals([{ unitPrice: '100', quantity: 1, discount: '100.01' }])).toBeNull()
    expect(
      computeTotals([{ unitPrice: '100', quantity: 1, discount: '100' }])?.grandTotalPaise,
    ).toBe(0)
    expect(computeTotals([])?.grandTotalPaise).toBe(0)
  })

  it('applies the free-discount rule to each line', () => {
    const line = (discount: string) => [{ unitPrice: '1000.00', quantity: 1, discount }]
    expect(discountProblem(line('100.00'), 10, false)).toBeNull() // exactly the limit
    expect(discountProblem(line('100.01'), 10, false)).toMatch(/manager/)
    expect(discountProblem(line('500.00'), 10, true)).toBeNull() // allowed with the permission
    expect(discountProblem(line('x'), 10, true)).toMatch(/amounts/)
    expect(discountProblem(line('1000.01'), 10, true)).toMatch(/more than/)
  })
})
