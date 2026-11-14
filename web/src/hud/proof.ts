import type { Proof } from './state'

export async function loadHudProof(): Promise<Proof | null> {
  try {
    const response = await fetch('/proof.json', { cache: 'no-store' })
    if (!response.ok) return null
    return await response.json()
  } catch {
    return null
  }
}
