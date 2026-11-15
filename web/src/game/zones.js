// Zone names for the game pages. The contract's four until /nodes.json (CONTRACTS.md section 3) says
// otherwise, so a new layout reaches both pages without a code change. No DOM in here.
export const ZONES = { 1: 'Bed', 2: 'Chair', 3: 'Hall', 4: 'Bathroom' }
export const CORNERS = { 1: 'NW', 2: 'NE', 3: 'SW', 4: 'SE' }
// Device names by node id ("east" -> "East beacon"), from nodes.json's nodes and hall beacons. Empty until it loads.
export const DEVICES = {}
const WORDS = { NW: 'north-west', NE: 'north-east', SW: 'south-west', SE: 'south-east', W: 'west', E: 'east' }
const ORDER = ['NW', 'NE', 'SW', 'SE', 'W', 'E']

// Take the zones from a parsed nodes.json. Returns false (and changes nothing) if it has none.
export function useZones(nodes) {
  const list = (Array.isArray(nodes?.zones) ? nodes.zones : [])
    .filter((z) => Number.isInteger(z?.id) && z.id > 0 && typeof z.name === 'string' && z.name.trim())
  if (!list.length) return false
  for (const k of Object.keys(ZONES)) delete ZONES[k]
  for (const k of Object.keys(CORNERS)) delete CORNERS[k]
  for (const z of list) {
    ZONES[z.id] = z.name.trim()
    const where = z.corner ?? z.side   // the square's zones have a corner, the desk strip's a side
    if (typeof where === 'string') CORNERS[z.id] = where
  }
  return true
}

// Take the device names from a parsed nodes.json: each node's name, and "Hall beacon H" for a hall beacon.
export function useDevices(nodes) {
  const named = (Array.isArray(nodes?.nodes) ? nodes.nodes : [])
    .filter((n) => typeof n?.id === 'string' && typeof n.name === 'string' && n.name.trim())
  const hall = (Array.isArray(nodes?.hall?.beacons) ? nodes.hall.beacons : [])
    .filter((b) => typeof b?.node === 'string' && typeof b.id === 'string' && b.id.trim())
  if (!named.length && !hall.length) return false
  for (const k of Object.keys(DEVICES)) delete DEVICES[k]
  for (const b of hall) DEVICES[b.node] = `Hall beacon ${b.id.trim()}`
  for (const n of named) DEVICES[n.id] = n.name.trim()
  return true
}

// A device in plain words, never its id.
export function deviceName(id) {
  return DEVICES[id] ?? 'A device'
}

// The zones in floor order (north-west first, or west first on a strip; by id when there's neither),
// each with the small line under its name: "Zone 1, north-west". One spot (a single zone) has no line under
// its name: there is no other zone to tell it from, so no number and no side.
export function zoneList() {
  const rank = (id) => (ORDER.includes(CORNERS[id]) ? ORDER.indexOf(CORNERS[id]) : ORDER.length)
  const one = Object.keys(ZONES).length === 1
  return Object.keys(ZONES).map(Number).sort((a, b) => rank(a) - rank(b) || a - b)
    .map((id) => ({ id, name: ZONES[id], hint: one ? '' : WORDS[CORNERS[id]] ? `Zone ${id}, ${WORDS[CORNERS[id]]}` : `Zone ${id}` }))
}

// The two words under the floor: which way is which. The square names the router's side; the desk strip
// is a row of zones, so it names its ends. One spot names nothing: the router sits beside the board at the
// desk there, so "South: the router" would be wrong, and there are no ends to name.
export function compass() {
  if (Object.keys(ZONES).length === 1) return []
  const sides = Object.values(CORNERS)
  if (sides.length && sides.every((c) => c === 'W' || c === 'E')) return ['West', 'East']
  return ['South: the router', 'North is up']
}

// A zone named as a place ("At the desk", "By the door") is said as it is, in a sentence: "at the desk".
// null for a zone with a plain name ("Chair"), which gets words around it, and for an unknown zone.
const PLACE = /^(at|in|on|by|near|behind|under) \S/i
export function placeName(z) {
  const name = ZONES[z]
  return name && PLACE.test(name) ? name.charAt(0).toLowerCase() + name.slice(1) : null
}

// Fetch /nodes.json from the board (or the dev server) and use its zones and device names. True if either was taken.
export async function loadZones(fetchFn = globalThis.fetch) {
  try {
    const reply = await fetchFn('/nodes.json', { cache: 'no-store' })
    if (!reply.ok) return false
    const nodes = await reply.json()
    const devices = useDevices(nodes)
    return useZones(nodes) || devices
  } catch {
    return false
  }
}
