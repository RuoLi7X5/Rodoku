export type Bitset = bigint[]

export function bitsetCreate(bitCount: number): Bitset {
  const chunks = Math.ceil(bitCount / 64)
  return new Array<bigint>(chunks).fill(0n)
}

export function bitsetClone(a: Bitset): Bitset {
  return a.slice()
}

export function bitsetSet(a: Bitset, idx: number): void {
  const c = Math.floor(idx / 64)
  const o = BigInt(idx % 64)
  a[c] = a[c] | (1n << o)
}

export function bitsetOrInto(dst: Bitset, src: Bitset): void {
  for (let i = 0; i < dst.length; i++) dst[i] |= src[i]
}

export function bitsetAndNonZero(a: Bitset, b: Bitset): boolean {
  for (let i = 0; i < a.length; i++) {
    if ((a[i] & b[i]) !== 0n) return true
  }
  return false
}

export function bitsetIsZero(a: Bitset): boolean {
  for (let i = 0; i < a.length; i++) if (a[i] !== 0n) return false
  return true
}

export function bitsetHas(a: Bitset, idx: number): boolean {
  const c = Math.floor(idx / 64)
  const o = BigInt(idx % 64)
  return (a[c] & (1n << o)) !== 0n
}

export function bitsetAnd(a: Bitset, b: Bitset): Bitset {
  const out = new Array<bigint>(a.length)
  for (let i = 0; i < a.length; i++) out[i] = a[i] & b[i]
  return out
}

export function bitsetNot(a: Bitset, bitCount: number): Bitset {
  const out = new Array<bigint>(a.length)
  for (let i = 0; i < a.length; i++) out[i] = ~a[i]
  // mask last chunk
  const rem = bitCount % 64
  if (rem !== 0) {
    const mask = (1n << BigInt(rem)) - 1n
    out[out.length - 1] &= mask
  }
  return out
}

export function bitsetAndNot(a: Bitset, b: Bitset): Bitset {
  const out = new Array<bigint>(a.length)
  for (let i = 0; i < a.length; i++) out[i] = a[i] & ~b[i]
  return out
}

export function bitsetEquals(a: Bitset, b: Bitset): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

export function bitsetPopFirst(a: Bitset): number | null {
  for (let i = 0; i < a.length; i++) {
    const v = a[i]
    if (v === 0n) continue
    // find lowest set bit
    for (let bit = 0; bit < 64; bit++) {
      if ((v & (1n << BigInt(bit))) !== 0n) return i * 64 + bit
    }
  }
  return null
}







