// Zone names for the game pages. The contract's four until /nodes.json (CONTRACTS.md section 3) says
// otherwise, so a new layout reaches both pages without a code change. No DOM in here.
export const ZONES = { 1: 'Bed', 2: 'Chair', 3: 'Hall', 4: 'Bathroom' }
export const CORNERS = { 1: 'NW', 2: 'NE', 3: 'SW', 4: 'SE' }
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

// The zones in floor order (north-west first, or west first on a strip; by id when there's neither),
// each with the small line under its name: "Zone 1, north-west".
export function zoneList() {
  const rank = (id) => (ORDER.includes(CORNERS[id]) ? ORDER.indexOf(CORNERS[id]) : ORDER.length)
  return Object.keys(ZONES).map(Number).sort((a, b) => rank(a) - rank(b) || a - b)
    .map((id) => ({ id, name: ZONES[id], hint: WORDS[CORNERS[id]] ? `Zone ${id}, ${WORDS[CORNERS[id]]}` : `Zone ${id}` }))
}

// The two words under the floor: which way is which. The square names the router's side; the desk strip
// is a row of zones, so it names its ends.
export function compass() {
  const sides = Object.values(CORNERS)
  if (sides.length && sides.every((c) => c === 'W' || c === 'E')) return ['West', 'East']
  return ['South: the router', 'North is up']
}

// Fetch /nodes.json from the board (or the dev server) and use its zones. True if they were taken.
export async function loadZones(fetchFn = globalThis.fetch) {
  try {
    const reply = await fetchFn('/nodes.json', { cache: 'no-store' })
    return reply.ok && useZones(await reply.json())
  } catch {
    return false
  }
}
