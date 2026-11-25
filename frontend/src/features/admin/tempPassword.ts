// No 0/O, 1/l/I: a password read out or copied by hand should not be ambiguous.
export const ALPHABET = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'

/**
 * A random temporary password like "kT7m-Qp3x-Wn9c-Vd4s" (16 characters plus dashes).
 * Uses the browser's cryptographic generator, and rejection sampling so every character is
 * equally likely (a plain modulo would favour the first few).
 */
type Bytes = Uint8Array<ArrayBuffer>

export function generateTempPassword(
  random: (a: Bytes) => Bytes = (a) => crypto.getRandomValues(a),
): string {
  const limit = 256 - (256 % ALPHABET.length) // bytes at or above this would bias the result
  const chars: string[] = []
  while (chars.length < 16) {
    for (const byte of random(new Uint8Array(32) as Bytes)) {
      if (byte < limit && chars.length < 16) chars.push(ALPHABET[byte % ALPHABET.length])
    }
  }
  return chars.join('').replace(/(.{4})(?=.)/g, '$1-')
}
