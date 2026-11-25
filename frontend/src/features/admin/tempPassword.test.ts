import { describe, expect, it } from 'vitest'
import { ALPHABET, generateTempPassword } from './tempPassword'

describe('temporary passwords', () => {
  it('are long enough for the server, grouped, and use only unambiguous characters', () => {
    for (let i = 0; i < 200; i++) {
      const p = generateTempPassword()
      expect(p).toMatch(/^[A-Za-z2-9]{4}(-[A-Za-z2-9]{4}){3}$/)
      expect(p.length).toBe(19) // 16 characters and 3 dashes, well over the 10 required
      expect(p).not.toMatch(/[01OlI]/)
    }
  })

  it('are different every time', () => {
    const seen = new Set(Array.from({ length: 2000 }, () => generateTempPassword()))
    expect(seen.size).toBe(2000)
  })

  it('make every character equally likely (no modulo bias)', () => {
    const counts = new Map<string, number>()
    const n = 20_000
    for (let i = 0; i < n; i++) {
      for (const c of generateTempPassword().replaceAll('-', ''))
        counts.set(c, (counts.get(c) ?? 0) + 1)
    }
    const expected = (n * 16) / ALPHABET.length
    for (const c of ALPHABET) {
      expect(counts.get(c) ?? 0).toBeGreaterThan(expected * 0.85)
      expect(counts.get(c) ?? 0).toBeLessThan(expected * 1.15)
    }
    expect([...counts.keys()].every((c) => ALPHABET.includes(c))).toBe(true)
  })

  it('discards biased bytes instead of wrapping them', () => {
    // A source that only returns bytes above the unbiased limit yields nothing until it changes.
    const limit = 256 - (256 % ALPHABET.length)
    let calls = 0
    const source = (a: Uint8Array<ArrayBuffer>) => {
      calls++
      a.fill(calls < 3 ? 255 : 0) // 255 is >= limit, so it is thrown away; 0 is accepted
      return a
    }
    expect(limit).toBeLessThan(256)
    expect(generateTempPassword(source).replaceAll('-', '')).toBe(ALPHABET[0].repeat(16))
    expect(calls).toBeGreaterThanOrEqual(3)
  })
})
