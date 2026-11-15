import type { AskLast, ChainInfo, EngineState, Layout, TailRecord } from './model'
import type { Scene } from './source'

// A simulated kit for the engine room: a chain that grows by one record a second, two witnesses that sign the
// head every 5 s, and the states that go with them. The page says "Simulated" whenever this plays. Nothing here
// is measured: the hashes are made up (not SHA-256) and so are the timings.
//
//   ?mock=running   everything working (the default)
//   ?mock=silent    one witness goes silent from 8 s to 30 s, then comes back; the chain goes on; loops every 45 s
//   ?mock=broken    the chain does not verify: it breaks 6 records back
//   ?mock=answer    running, with a detective's answer that cites records in the strip
//   ?mock=nowitness no witness is enrolled: the board seals alone
//   ?mock=badsig    the last witness's signature does not check
//   ?mock=none      no board: nothing answers

export const ENGINE_SCENES = ['running', 'silent', 'broken', 'answer', 'nowitness', 'badsig', 'none'] as const
export type EngineScene = (typeof ENGINE_SCENES)[number]

export function engineScene(name: string | null): EngineScene {
  return (ENGINE_SCENES as readonly string[]).includes(name ?? '') ? (name as EngineScene) : 'running'
}

/** The kit the simulated scenes play on when no layout file is at hand: the gate's three devices. */
export const MOCK_LAYOUT: Layout = {
  nodes: [
    { id: 'unoq', name: 'Board', device: 'unoq', roles: ['receiver'] },
    { id: 'pi5', name: 'Pi A', device: 'pi5', roles: ['router', 'beacon', 'receiver'] },
    { id: 'pi5b', name: 'Pi B', device: 'pi5', roles: ['beacon', 'receiver'] },
  ],
  links: [
    { id: 'pi5>unoq:wifi', tx: 'pi5', rx: 'unoq', kind: 'wifi' },
    { id: 'pi5>unoq:ble', tx: 'pi5', rx: 'unoq', kind: 'ble' },
    { id: 'pi5b>unoq:ble', tx: 'pi5b', rx: 'unoq', kind: 'ble' },
    { id: 'pi5>pi5b:wifi', tx: 'pi5', rx: 'pi5b', kind: 'wifi' },
    { id: 'pi5>pi5b:ble', tx: 'pi5', rx: 'pi5b', kind: 'ble' },
    { id: 'pi5b>pi5:ble', tx: 'pi5b', rx: 'pi5', kind: 'ble' },
  ],
}

/** A made-up 64-character hash for a record number: the same number always gives the same hash. */
export function fakeHash(seq: number): string {
  let x = (seq * 2654435761) >>> 0
  let out = ''
  for (let i = 0; i < 8; i++) {
    x = (Math.imul(x ^ (x >>> 15), 2246822519) + 0x9e3779b9) >>> 0
    out += x.toString(16).padStart(8, '0')
  }
  return out
}

const START_T = Date.UTC(2026, 10, 15, 9, 41, 0) // the simulated board's clock when the scene starts
const START_SEQ = 1180
const SIGN_EVERY_S = 5
const RUNNING_BEFORE_S = 30
const SILENT_FROM_S = 8
const SILENT_TO_S = 30
const SILENT_LOOP_S = 45
/** A witness is called silent after 15 s without a signature (the witness wording). */
const SILENT_AFTER_S = 15

/** The devices that sign the record: the Pis (a beacon with no computer in it cannot sign). */
export function witnessIds(layout: Layout): string[] {
  const pis = layout.nodes.filter((n) => n.device.startsWith('pi')).map((n) => n.id)
  return pis.length ? pis : layout.nodes.filter((n) => n.device !== 'unoq').slice(0, 2).map((n) => n.id)
}

interface Rec { seq: number; t: number; kind: string; node: string | null; for_seq: number | null }

/** Whether a witness signs at second `s` of the scene. */
function signs(scene: EngineScene, node: string, witnesses: readonly string[], s: number): boolean {
  if (scene !== 'silent' || node !== witnesses.at(-1) || s < 0) return true
  const at = s % SILENT_LOOP_S
  return at < SILENT_FROM_S || at >= SILENT_TO_S
}

/**
 * Every record sealed from the scene's start to second `upTo`: one record a second (kind "second"), a signature from each
 * witness that is signing every 5 s (each vouching for the summary of that second), and "witness silent" /
 * "witness back" once each when one stops and starts.
 */
export function records(scene: EngineScene, layout: Layout, upTo: number, from = 0): Rec[] {
  const witnesses = scene === 'nowitness' ? [] : witnessIds(layout)
  const out: Rec[] = []
  let seq = START_SEQ
  const lastSigned = new Map(witnesses.map((w) => [w, from]))
  const silent = new Set<string>()
  for (let s = from; s <= upTo; s++) {
    const t = START_T + s * 1000
    out.push({ seq: ++seq, t, kind: 'second', node: null, for_seq: null })
    const head = seq
    for (const w of witnesses) {
      if (((s % SIGN_EVERY_S) + SIGN_EVERY_S) % SIGN_EVERY_S === 0 && signs(scene, w, witnesses, s)) {
        if (silent.delete(w)) out.push({ seq: ++seq, t, kind: 'witness_back', node: w, for_seq: null })
        out.push({ seq: ++seq, t, kind: 'witness', node: w, for_seq: head })
        lastSigned.set(w, s)
      } else if (!silent.has(w) && s - lastSigned.get(w)! >= SILENT_AFTER_S) {
        silent.add(w)
        out.push({ seq: ++seq, t, kind: 'witness_silent', node: w, for_seq: null })
      }
    }
  }
  return out
}

/** Everything the simulated kit says `tMs` into the scene. */
export function sceneAt(scene: EngineScene, tMs: number, layout: Layout = MOCK_LAYOUT): Scene {
  if (scene === 'none') return { layout, state: null, chain: null, tail: null, ask: null, privacy: null, prove: null }
  const s = Math.floor(tMs / 1000)
  const now = START_T + tMs
  // The kit was running before the page opened: half a minute of records is already there.
  const all = records(scene, layout, s, -RUNNING_BEFORE_S)
  const head = all.at(-1)!
  const witnesses = scene === 'nowitness' ? [] : witnessIds(layout)
  const last = (keep: (r: Rec) => boolean) => all.filter(keep).at(-1) ?? null
  const lastOf = (w: string) => last((r) => r.kind === 'witness' && r.node === w)
  const isSilent = (w: string) => {
    const back = last((r) => (r.kind === 'witness_silent' || r.kind === 'witness_back') && r.node === w)
    return back?.kind === 'witness_silent'
  }
  const firstBad = scene === 'broken' ? Math.max(START_SEQ + 1, head.seq - 6) : null
  // The board verifies every 30 s; the first check lands 2 s in.
  const verifiedS = s < 2 ? null : s - ((s - 2) % 30)
  const chain: ChainInfo = {
    head: { seq: head.seq, hash: fakeHash(head.seq) },
    records: head.seq,
    since_t: START_T - START_SEQ * 1000,
    verified: firstBad !== null ? false : verifiedS === null ? 'checking' : true,
    last_verify_t: verifiedS === null ? null : START_T + verifiedS * 1000,
    first_bad_seq: firstBad,
    witnesses: witnesses.map((w) => ({ node: w, last_seq: lastOf(w)?.for_seq ?? null, last_t: lastOf(w)?.t ?? null, sig_ok: !(scene === 'badsig' && w === witnesses.at(-1)), silent: isSilent(w) })),
    last_verify_checked: verifiedS === null ? null : 600,
    last_verify_ms: verifiedS === null ? null : 3,
  }
  const tail: TailRecord[] = all.slice(-40).map((r) => ({ ...r, hash: fakeHash(r.seq) }))
  // A witness that is silent has dropped off the network: the lines to and from it read nothing.
  const off = new Set(witnesses.filter((w) => !signs(scene, w, witnesses, s)))
  const state: EngineState = {
    t: now,
    cam: 'off',
    links: layout.links.map((l, i) => {
      const quiet = off.has(l.tx) || off.has(l.rx)
      const base = l.kind === 'wifi' ? 25 : 6
      return { id: l.id, rate_hz: quiet ? 0 : Math.round((base + Math.sin(tMs / 900 + i) * (l.kind === 'wifi' ? 0.4 : 1.5)) * 10) / 10, status: quiet ? 'stale' : 'ok' }
    }),
    model: { ms_per_decision: 3.1, train_s: null },
    chain: { seq: head.seq, hash8: fakeHash(head.seq).slice(0, 8), verified: chain.verified === true, witnesses_ok: chain.witnesses.filter((w) => !w.silent).length, witnesses: witnesses.length },
  }
  const summaries = all.filter((r) => r.kind === 'second').slice(-14, -4)
  const ask: AskLast | null =
    // Once there are records to cite (the first seconds of a scene have too few).
    scene === 'answer' && summaries.length >= 2
      ? {
          question: 'What happened in the last minute?',
          // The shape the board's detective gives: a story of several sentences, its five steps, and every
          // record the story rests on (more than fit in a line, and more than the panel shows of the story).
          answer:
            'Nobody was on the spot in the last minute. No alert went off. Both witnesses signed throughout, every 5 seconds, with no gap in either one. The board sealed one record a second, and every seal checked against the one before it.',
          steps: [
            { tool: 'fetch events', ms: 0.2, rows: 0 },
            { tool: 'fetch summaries', ms: 1.1, rows: 60 },
            { tool: 'line up the timeline', ms: 0.2, rows: 1 },
            { tool: 'verify the chain', ms: 0.9, rows: 60 },
            { tool: 'write the story', ms: 0.1, rows: 1 },
          ],
          cites: summaries.map((r) => r.seq),
          chain_ok: true,
        }
      : null
  return {
    layout, state, chain, tail, ask,
    privacy: null, // nothing is measured in a simulation, so no numbers are shown for it
    prove: { ok: false, altered_seq: Math.max(all[0].seq, head.seq - 9), first_bad_seq: Math.max(all[0].seq, head.seq - 9), ms: 2 },
  }
}
