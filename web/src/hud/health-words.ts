import type { StateMsg } from '../room/contract'
import { hudLayout, type HudLayout } from './layout'

export function blindSentence(state: StateMsg, layout: HudLayout = hudLayout) {
  const blind = new Set(state.health.blind)
  const missing = layout.nodes.filter(node => {
    const links = layout.links.filter(link => link.tx === node.id || link.rx === node.id)
    return links.length > 0 && links.every(link => blind.has(link.id))
  })
  // Do not blame an endpoint when the failed links do not identify it.
  if (!missing.length) return 'A radio link is not heard.'
  const names = missing.map(node => node.name?.trim() || 'A device')
  const named = names.length < 3 ? names.join(' and ') : `${names.slice(0,-1).join(', ')} and ${names.at(-1)}`
  const pi = missing.some(node => /^Pi\b/i.test(node.name ?? ''))
  const check = names.length === 1 ? (pi ? 'Check it is on the hotspot.' : 'Check its power.') : (pi ? 'Check their power and network.' : 'Check their power.')
  return `${named} not heard. ${check}`
}
const published = new WeakMap<HTMLElement,string>()
/** The room can consume the same words without importing a HUD module. */
export function publishHealth(root: HTMLElement, state: StateMsg | null, stale: boolean) {
  const blind = !stale && state?.health.status === 'blind'
  const tamper = !stale && !!state?.armed && !!state.tamper?.length
  const sentence = blind && state ? blindSentence(state) : ''
  root.dataset.healthSentence = sentence
  root.dataset.tamperHeadline = String(tamper)
  const detail = { sentence, blind, tamper }, key = JSON.stringify(detail)
  if (published.get(root) === key) return
  published.set(root,key)
  window.dispatchEvent(new CustomEvent('hud:health',{detail}))
}
