import file from '../../../radio/nodes.json'
export interface HudLayout {
  nodes: { id: string; name?: string; xyz_m: number[] }[]
  /** crosses_spot (a one-spot layout): the line runs through the place a person stands. Missing = not said. */
  links: { id: string; tx: string; rx: string; kind: string; crosses_spot?: boolean }[]
  zones: { id: number; name: string; still_alert_s: number | null }[]
  router_spots: { id: string; xyz_m: number[] }[]
}
export let hudLayout: HudLayout = file
let pending: Promise<void> | undefined
export function loadHudLayout() {
  return pending ??= (async () => {
    try {
      const response = await fetch('/nodes.json', { signal: AbortSignal.timeout(2000) })
      if (!response.ok) return
      const value = await response.json()
      if (Array.isArray(value.nodes) && Array.isArray(value.links) && value.zones?.every((z: { id: number; name: string }) => Number.isInteger(z.id) && typeof z.name === 'string') && value.zones.length) hudLayout = value
    } catch { /* The bundled layout remains available offline. */ }
  })()
}
export function zoneName(id: number | null | undefined, layout = hudLayout) {
  return layout.zones.find(zone => zone.id === id)?.name ?? 'the desk'
}
const places: Record<string, string> = { Bed: 'by the bed', Chair: 'at the chair', Hall: 'in the hall', Bathroom: 'in the bathroom' }
export function zonePlace(id: number | null | undefined, layout = hudLayout) {
  const name = zoneName(id, layout)
  if (/^(left|right)$/i.test(name)) return `on the ${name.toLowerCase()}`
  // A zone named as a place ("At the desk", "By the door") is said as it is.
  if (/^(at|in|on|by|near|behind|under) \S/i.test(name)) return name.charAt(0).toLowerCase() + name.slice(1)
  return places[name] ?? 'at the desk'
}
/** Where the camera sees someone: "in Left" for a zone with a plain name, "at the desk" for one named as a place. */
export function zoneIn(id: number | null | undefined, layout = hudLayout) {
  const name = zoneName(id, layout)
  return /^(at|in|on|by|near|behind|under) \S/i.test(name) ? zonePlace(id, layout) : `in ${name}`
}
export function linkName(id: string, layout = hudLayout) {
  const [pair, kind] = id.split(':')
  const [tx, rx] = pair.split('>')
  const link = layout.links.find(link => link.id === id)
  const name = (node: string) => layout.nodes.find(item => item.id === node)?.name || node
  return `${name(link?.tx ?? tx)} to ${name(link?.rx ?? rx ?? '')}, ${(link?.kind ?? kind) === 'wifi' ? 'Wi-Fi' : (link?.kind ?? kind) === 'ble' ? 'Bluetooth' : kind ?? ''}`
}
