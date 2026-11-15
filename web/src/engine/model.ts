// The engine room's facts, as plain functions: what the board says (GET /chain and friends, the state on the
// WebSocket, the layout file) turned into the words and numbers the screen shows. Nothing here touches the page.
// Shapes follow the witness wording (the contract issue "Witness: the sealed record, the witnesses and the
// detective"); every field the board may not send yet is optional and its line is simply left off the screen.

export interface Witness {
  node: string
  last_seq: number | null
  last_t: number | null
  sig_ok: boolean
  silent: boolean
}

/** GET /chain. */
export interface ChainInfo {
  head: { seq: number; hash: string }
  records: number
  since_t: number | null
  verified: boolean | 'checking'
  last_verify_t: number | null
  first_bad_seq: number | null
  witnesses: Witness[]
  /** Optional: how many records the last verify checked and how long it took. */
  last_verify_checked: number | null
  last_verify_ms: number | null
}

/** One sealed record, as the strip draws it (GET /chain/tail). A signature names the record it vouches for. */
export interface TailRecord {
  seq: number
  t: number | null
  kind: string
  hash: string
  node: string | null
  for_seq: number | null
}

/** POST /chain/prove: a copy with one record altered, verified. The real log is never touched. */
export interface ProveResult {
  ok: boolean
  altered_seq: number
  first_bad_seq: number
  ms: number | null
}

/** The detective's last answer (the Ask answer's steps, cites and chain_ok). */
export interface AskLast {
  question: string | null
  answer: string
  steps: { tool: string; ms: number | null; rows: number | null }[]
  cites: number[]
  chain_ok: boolean | null
}

/** GET /privacy: the meter's numbers, or the board's own reason for having none. */
export type Privacy = { images: number; bytes_out: number } | { why: string }

/** What the engine room reads from a state message. */
export interface EngineState {
  t: number
  cam?: string
  links?: { id: string; rate_hz: number | null; status: string }[]
  model?: { ms_per_decision: number | null; train_s: number | null } | null
  narration?: { gen_ms?: number | null } | null
  chain?: { seq: number; hash8: string; verified: boolean; witnesses_ok: number; witnesses: number } | null
}

export interface LayoutNode { id: string; name: string; device: string; roles: string[] }
export interface LayoutLink { id: string; tx: string; rx: string; kind: string }
export interface Layout { nodes: LayoutNode[]; links: LayoutLink[] }

type Json = Record<string, unknown>
const obj = (v: unknown): v is Json => !!v && typeof v === 'object' && !Array.isArray(v)
const int = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0
const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0
const hex = (v: unknown): v is string => typeof v === 'string' && /^[0-9a-f]{8,64}$/i.test(v)

export function parseLayout(v: unknown): Layout | null {
  if (!obj(v) || !Array.isArray(v.nodes) || !Array.isArray(v.links)) return null
  const nodes: LayoutNode[] = []
  for (const n of v.nodes) {
    if (!obj(n) || typeof n.id !== 'string') return null
    nodes.push({
      id: n.id,
      name: typeof n.name === 'string' && n.name.trim() ? n.name.trim() : n.id,
      device: typeof n.device === 'string' ? n.device : '',
      roles: Array.isArray(n.roles) ? n.roles.filter((r): r is string => typeof r === 'string') : [],
    })
  }
  const links: LayoutLink[] = []
  for (const l of v.links) {
    if (!obj(l) || typeof l.id !== 'string' || typeof l.tx !== 'string' || typeof l.rx !== 'string') return null
    links.push({ id: l.id, tx: l.tx, rx: l.rx, kind: typeof l.kind === 'string' ? l.kind : '' })
  }
  return nodes.length ? { nodes, links } : null
}

export function parseChain(v: unknown): ChainInfo | null {
  if (!obj(v) || !obj(v.head) || !int(v.head.seq) || !hex(v.head.hash) || !int(v.records)) return null
  const verified = v.verified === true || v.verified === false || v.verified === 'checking' ? v.verified : null
  if (verified === null) return null
  const witnesses: Witness[] = []
  for (const w of Array.isArray(v.witnesses) ? v.witnesses : []) {
    if (!obj(w) || typeof w.node !== 'string') continue
    witnesses.push({ node: w.node, last_seq: int(w.last_seq) ? w.last_seq : null, last_t: num(w.last_t) ? w.last_t : null, sig_ok: w.sig_ok === true, silent: w.silent === true })
  }
  return {
    head: { seq: v.head.seq, hash: v.head.hash.toLowerCase() },
    records: v.records,
    since_t: num(v.since_t) ? v.since_t : null,
    verified,
    last_verify_t: num(v.last_verify_t) ? v.last_verify_t : null,
    first_bad_seq: int(v.first_bad_seq) ? v.first_bad_seq : null,
    witnesses,
    last_verify_checked: int(v.last_verify_checked) ? v.last_verify_checked : null,
    last_verify_ms: num(v.last_verify_ms) ? v.last_verify_ms : null,
  }
}

export function parseTail(v: unknown): TailRecord[] | null {
  const rows = obj(v) && Array.isArray(v.records) ? v.records : v
  if (!Array.isArray(rows)) return null
  const out: TailRecord[] = []
  for (const r of rows) {
    if (!obj(r) || !int(r.seq) || typeof r.kind !== 'string') continue
    const hash = hex(r.hash) ? r.hash : hex(r.hash8) ? r.hash8 : null
    if (!hash) continue
    out.push({ seq: r.seq, t: num(r.t) ? r.t : null, kind: r.kind, hash: hash.toLowerCase(), node: typeof r.node === 'string' ? r.node : null, for_seq: int(r.for_seq) ? r.for_seq : null })
  }
  return out.sort((a, b) => a.seq - b.seq)
}

export function parseProve(v: unknown): ProveResult | null {
  if (!obj(v) || typeof v.ok !== 'boolean' || !int(v.altered_seq) || !int(v.first_bad_seq)) return null
  return { ok: v.ok, altered_seq: v.altered_seq, first_bad_seq: v.first_bad_seq, ms: num(v.ms) ? v.ms : null }
}

export function parseAsk(v: unknown): AskLast | null {
  if (!obj(v) || typeof v.answer !== 'string' || !v.answer.trim()) return null
  const steps: AskLast['steps'] = []
  for (const s of Array.isArray(v.steps) ? v.steps : []) {
    if (obj(s) && typeof s.tool === 'string') steps.push({ tool: s.tool, ms: num(s.ms) ? s.ms : null, rows: int(s.rows) ? s.rows : null })
  }
  return {
    question: typeof v.question === 'string' && v.question.trim() ? v.question.trim() : null,
    answer: v.answer.trim(),
    steps,
    cites: (Array.isArray(v.cites) ? v.cites : []).filter(int),
    chain_ok: typeof v.chain_ok === 'boolean' ? v.chain_ok : null,
  }
}

export function parsePrivacy(v: unknown): Privacy | null {
  if (!obj(v)) return null
  if (v.ok === true && int(v.images) && int(v.bytes_out)) return { images: v.images, bytes_out: v.bytes_out }
  return v.ok === false && typeof v.why === 'string' && v.why.trim() ? { why: v.why.trim() } : null
}

/** "1,187": a count as people read it. */
export const count = (n: number) => Math.round(n).toLocaleString('en-US')

/** The first 8 characters of a hash, in two groups of four so a change is easy to see. */
export function hash8(hash: string): string {
  const h = hash.slice(0, 8)
  return `${h.slice(0, 4)} ${h.slice(4)}`
}

/** How long ago, in words a glance takes in: "now", "2 s ago", "3 min ago", "2 h ago". */
export function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 1) return 'now'
  if (s < 90) return `${s} s ago`
  if (s < 90 * 60) return `${Math.round(s / 60)} min ago`
  return `${Math.round(s / 3600)} h ago`
}

/** How long something has been quiet: "12 s", "3 min". */
export function span(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  return s < 90 ? `${s} s` : s < 90 * 60 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`
}

const KIND_WORDS: Record<string, string> = {
  second: 'second', // the once-a-second record (contract section 13)
  summary: 'second',
  witness: 'signature',
  witness_bad: 'bad signature',
  witness_silent: 'witness silent',
  witness_back: 'witness back',
  enter: 'entered',
  exit: 'left',
  alert_on: 'no movement',
  alert_off: 'alert over',
  checkin: 'check-in',
  intrusion: 'intrusion',
  passed_by: 'passed by',
  tamper: 'tamper',
  object_on: 'thing in line',
  object_off: 'line clear',
  arm: 'armed',
  disarm: 'disarmed',
}

/** A record's kind as a word a person reads; an unknown kind is shown as it is, with spaces. */
export function kindWord(kind: string): string {
  return KIND_WORDS[kind] ?? kind.replace(/_/g, ' ')
}

/** How many of the lines a device hears are listed in its column before "and N more". */
export const HEARS_SHOWN = 3

/** A device's lines as the column lists them: the first few, then how many more there are. */
export function hearsLines(hears: DeviceView['hears']): string[] {
  const lines = hears.map((h) => `${h.from} over ${h.radio}: ${h.hz === null ? 'no reading' : `${h.hz} a second`}`)
  return lines.length <= HEARS_SHOWN ? lines : [...lines.slice(0, HEARS_SHOWN - 1), `and ${lines.length - HEARS_SHOWN + 1} more lines`]
}

/** How many cited records are named one by one before the line gives their count and range instead. */
export const CITES_SHOWN = 6

/**
 * The records an answer cites, as one short line. A story over a few minutes cites dozens of records: named one
 * by one they fill the panel and push the steps out of sight, so beyond six the line gives how many and from
 * which record to which. The strip still marks each cited record that is on it.
 */
export function citesWords(cites: readonly number[]): string {
  if (!cites.length) return 'Cites no record'
  if (cites.length === 1) return `Cites record #${count(cites[0])}`
  if (cites.length <= CITES_SHOWN) return `Cites records ${cites.map((c) => `#${count(c)}`).join(', ')}`
  return `Cites ${count(cites.length)} records, #${count(Math.min(...cites))} to #${count(Math.max(...cites))}`
}

/** A tool's name as words: "still_spans" -> "still spans". */
export const toolWord = (tool: string) => tool.replace(/_/g, ' ')

const RADIO: Record<string, string> = { wifi: 'Wi-Fi', ble: 'Bluetooth' }

export interface DeviceView {
  id: string
  name: string
  /** The device that seals the record (it does not sign it). */
  board: boolean
  /** What it does, in a few words. */
  does: string
  /** The lines it hears: who, over which radio, and how many readings a second (null: no reading). */
  hears: { from: string; radio: string; hz: number | null }[]
  /** All its readings a second, or null when it hears no line (or nothing is known yet). */
  hz: number | null
  heard: boolean
  /** How long it has not been heard, in words, when it is not. */
  quiet: string | null
  /** For a witness: what it last signed. Null for the board, which seals and does not sign. */
  witness: { seq: number | null; ago: string | null; ok: boolean; silent: boolean; quiet: string | null } | null
}

/** The device that seals the record: the one the layout marks as the board (device "unoq"), else the first that
 *  is not a witness. */
export function boardId(layout: Layout, witnesses: readonly Witness[]): string | null {
  const signs = new Set(witnesses.map((w) => w.node))
  return (layout.nodes.find((n) => n.device === 'unoq') ?? layout.nodes.find((n) => !signs.has(n.id)))?.id ?? null
}

/** The devices the board hears now: one end of a line that is giving readings. */
export function heardNow(layout: Layout, links: NonNullable<EngineState['links']>): Set<string> {
  const live = new Set(links.filter((l) => (l.rate_hz ?? 0) > 0 && l.status !== 'blind' && l.status !== 'stale').map((l) => l.id))
  const out = new Set<string>()
  for (const l of layout.links) {
    if (live.has(l.id)) {
      out.add(l.tx)
      out.add(l.rx)
    }
  }
  return out
}

/**
 * One column per device, in the layout's order with the board first. `now` is the board's clock (the latest
 * state's t, carried forward); `heardAt` is when each device was last heard on that clock (kept by the page).
 */
export function deviceViews(layout: Layout, state: EngineState | null, chain: ChainInfo | null, now: number, heardAt: ReadonlyMap<string, number>): DeviceView[] {
  const witnesses = chain?.witnesses ?? []
  const board = boardId(layout, witnesses)
  const name = (id: string) => layout.nodes.find((n) => n.id === id)?.name ?? id
  const rate = new Map((state?.links ?? []).map((l) => [l.id, l]))
  const heard = state ? heardNow(layout, state.links ?? []) : new Set<string>()
  const nodes = [...layout.nodes].sort((a, b) => Number(b.id === board) - Number(a.id === board))
  return nodes.map((n) => {
    const hears = layout.links.filter((l) => l.rx === n.id).map((l) => {
      const row = rate.get(l.id)
      return { from: name(l.tx), radio: RADIO[l.kind] ?? l.kind, hz: row && row.status !== 'blind' ? row.rate_hz : null }
    })
    const known = hears.filter((h) => h.hz !== null)
    const w = witnesses.find((x) => x.node === n.id)
    const isBoard = n.id === board
    // The board is heard whenever its states arrive: it is the one talking to this page.
    const isHeard = isBoard ? !!state : heard.has(n.id)
    const last = heardAt.get(n.id)
    return {
      id: n.id,
      name: n.name,
      board: isBoard,
      does: isBoard
        ? 'Senses, decides, seals the record'
        : n.roles.includes('router')
          ? 'The Wi-Fi of the room'
          : n.roles.includes('receiver')
            ? 'Listens across the gap'
            : 'Sends a signal the others hear', // a beacon: no computer in it, so it hears nothing and signs nothing
      hears,
      hz: known.length ? Math.round(known.reduce((s, h) => s + (h.hz ?? 0), 0) * 10) / 10 : null,
      heard: isHeard,
      quiet: isHeard ? null : last === undefined ? 'not heard yet' : `not heard for ${span(now - last)}`,
      witness: w
        ? {
            seq: w.last_seq,
            ago: w.last_t === null ? null : ago(now - w.last_t),
            ok: w.sig_ok,
            silent: w.silent,
            quiet: w.silent ? (w.last_t === null ? 'has not signed yet' : `has not signed for ${span(now - w.last_t)}`) : null,
          }
        : null,
    }
  })
}

export interface Headline { label: string; value: string; note: string; fault: boolean }

/** The three numbers read from across the desk: the head record, the witnesses signing, the last verify. */
export function headlines(chain: ChainInfo | null, layout: Layout | null, now: number): Headline[] {
  if (!chain) {
    const none = { value: '__', note: 'no answer from the board', fault: false }
    return [{ label: 'Sealed record', ...none }, { label: 'Witnesses signing', ...none }, { label: 'Chain verified', ...none }]
  }
  const name = (id: string) => layout?.nodes.find((n) => n.id === id)?.name ?? id
  const signing = chain.witnesses.filter((w) => !w.silent && w.sig_ok)
  const silent = chain.witnesses.filter((w) => w.silent || !w.sig_ok)
  const since = chain.since_t === null ? '' : ` since ${new Date(chain.since_t).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`
  const checked = [chain.last_verify_checked === null ? null : `${count(chain.last_verify_checked)} records checked`, chain.last_verify_ms === null ? null : `${chain.last_verify_ms} ms`].filter(Boolean).join(' in ')
  const verify: Headline =
    chain.verified === false
      ? { label: 'Chain verified', value: 'No', note: chain.first_bad_seq === null ? 'the chain does not verify' : `the chain breaks at record #${count(chain.first_bad_seq)}`, fault: true }
      : chain.verified === 'checking' || chain.last_verify_t === null
        ? { label: 'Chain verified', value: 'Checking', note: 'the first check is running', fault: false }
        : { label: 'Chain verified', value: ago(now - chain.last_verify_t), note: checked || 'every record follows the one before', fault: false }
  return [
    { label: 'Sealed record', value: `#${count(chain.head.seq)}`, note: `${hash8(chain.head.hash)} · ${count(chain.records)} sealed${since}`, fault: false },
    {
      label: 'Witnesses signing',
      value: chain.witnesses.length ? `${signing.length} of ${chain.witnesses.length}` : '__',
      note: !chain.witnesses.length ? 'no witness is enrolled' : silent.length ? `${silent.map((w) => name(w.node)).join(' and ')} silent: the chain goes on` : chain.witnesses.map((w) => name(w.node)).join(' and '),
      fault: silent.length > 0,
    },
    verify,
  ]
}

export interface Block {
  seq: number
  word: string
  hash: string
  /** The witnesses that signed this record's hash, by name. */
  signed: string[]
  cited: boolean
  /** The chain does not verify from here on. */
  bad: boolean
}

/** The strip: the last `n` records as blocks, oldest first, each with the marks of the witnesses that vouch for it. */
export function blocks(tail: readonly TailRecord[], layout: Layout | null, cites: readonly number[], firstBad: number | null, n = 20): Block[] {
  const name = (id: string) => layout?.nodes.find((x) => x.id === id)?.name ?? id
  const marks = new Map<number, string[]>()
  for (const r of tail) {
    if (r.kind === 'witness' && r.for_seq !== null && r.node) marks.set(r.for_seq, [...(marks.get(r.for_seq) ?? []), name(r.node)])
  }
  const cited = new Set(cites)
  return tail.slice(-n).map((r) => ({
    seq: r.seq,
    word: r.kind === 'witness' && r.node ? `${name(r.node)} signed` : kindWord(r.kind),
    hash: r.hash.slice(0, 6),
    signed: [...new Set(marks.get(r.seq) ?? [])],
    cited: cited.has(r.seq),
    bad: firstBad !== null && r.seq >= firstBad,
  }))
}

/**
 * Which record the prove-it check should alter, so the result can be drawn: one that is on the strip, a few back
 * from the head, in a copy of just the records the strip holds. Null with no strip to draw it on (the board then
 * picks one itself).
 */
export function proveAsk(tail: readonly TailRecord[] | null): { n: number; seq: number } | null {
  if (!tail || tail.length < 8) return null
  return { n: tail.length, seq: tail[tail.length - 6].seq }
}

/** With no tail from the board: the heads this page has seen go by, as blocks with no kind (it was not told). */
export function seenHeads(seen: readonly { seq: number; hash: string }[], head: { seq: number; hash: string } | null): { seq: number; hash: string }[] {
  if (!head || seen.at(-1)?.seq === head.seq) return [...seen]
  // A head lower than the last one seen is another log (the board restarted): start again.
  const kept = seen.length && head.seq < seen.at(-1)!.seq ? [] : [...seen]
  return [...kept, { seq: head.seq, hash: head.hash }].slice(-40)
}

/**
 * What the prove-it check found, in one sentence, exactly as the board reported it. A copy that no longer
 * verifies is the check working (the altered block is what is drawn in the fault colour); a copy that still
 * verifies after being altered is the fault, and is said as one.
 */
export function proveWords(r: ProveResult): { words: string; fault: boolean } {
  const took = r.ms === null ? '' : ` Checked in ${r.ms} ms.`
  if (r.ok) return { words: `The board altered record #${count(r.altered_seq)} in a copy and the copy still verified. That is a fault: tell the team.${took}`, fault: true }
  const where = r.first_bad_seq === r.altered_seq ? 'the chain breaks here' : `the chain breaks at record #${count(r.first_bad_seq)}`
  return { words: `Record #${count(r.altered_seq)} was altered in a copy: ${where}. The real record is untouched.${took}`, fault: false }
}

/** The model timings the board reports, each with its number; nothing for one it has not measured. */
export function timings(state: EngineState | null, ask: AskLast | null): string[] {
  const out: string[] = []
  const m = state?.model
  if (m && m.ms_per_decision !== null) out.push(`Decision ${m.ms_per_decision} ms`)
  const gen = state?.narration?.gen_ms
  if (typeof gen === 'number' && gen > 0) out.push(`Sentence ${gen} ms`)
  const total = ask?.steps.reduce((s, x) => s + (x.ms ?? 0), 0) ?? 0
  if (ask && total > 0) out.push(`Answer ${Math.round(total)} ms`)
  return out
}

/**
 * The always-on line: what is and is not watching. The camera's state is the board's own word; the kit has no
 * microphone on any device (a fact of the build, not a reading); images stored and bytes out are the privacy
 * meter's numbers, and never a zero it has not measured.
 */
export function watchLine(state: EngineState | null, privacy: Privacy | null, simulated = false): string[] {
  const cam = !state ? 'Camera: __' : state.cam === 'off' ? '0 cameras' : state.cam === 'on' ? 'Camera ON' : 'Camera state unknown'
  const meter = !privacy
    ? [simulated ? 'privacy meter: simulated, nothing measured' : 'privacy meter not answering']
    : 'why' in privacy
      ? [privacy.why] // the board's own words: "privacy meter is not running"
      : [`${count(privacy.images)} images stored`, `${count(privacy.bytes_out)} bytes out`]
  return [cam, 'No microphone on any device', ...meter]
}
