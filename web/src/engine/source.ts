import { feedFrom, wsTransport, type Feed, type Transport } from '../room/feed'
import { parseAsk, parseChain, parseLayout, parsePrivacy, parseProve, parseTail, type AskLast, type ChainInfo, type EngineState, type Layout, type Privacy, type ProveResult, type TailRecord } from './model'

// Where the engine room's facts come from: the board (its WebSocket and its web server), or a simulated kit
// (mock.ts) when there is no board. The page asks the same questions of either. A question the board has no
// answer for yet (an endpoint that is not there) comes back null and its part of the screen says so or stays off.

export interface Source {
  kind: 'board' | 'mock'
  feed: Feed
  layout(): Promise<Layout | null>
  chain(): Promise<ChainInfo | null>
  /** The last `n` sealed records, or null when the board does not offer them. */
  tail(n: number): Promise<TailRecord[] | null>
  /** Asks the board to alter one record in a COPY and verify it (`ask` picks the copy's size and the record).
   *  Null: the board did not answer. `{ error }`: it answered that it could not, in its own words. */
  prove(ask?: { n: number; seq: number } | null): Promise<ProveResult | { error: string } | null>
  lastAsk(): Promise<AskLast | null>
  privacy(): Promise<Privacy | null>
}

/** The state the feed holds, as the engine room reads it. */
export const engineState = (feed: Feed): EngineState | null => feed.current().state as unknown as EngineState | null

async function getJson(url: string, init?: RequestInit): Promise<unknown> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), 2500)
  try {
    const res = await fetch(url, { cache: 'no-store', headers: { accept: 'application/json' }, signal: abort.signal, ...init })
    return res.ok ? await res.json() : null
  } catch {
    return null // no board, a slow answer, or an answer that is not JSON: there is nothing to show
  } finally {
    clearTimeout(timer)
  }
}

/** POST /chain/prove. The board's refusals come with its reason ({"error": "..."}: no sealed record yet). */
async function postProve(ask: object): Promise<ProveResult | { error: string } | null> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), 5000)
  try {
    const res = await fetch('/chain/prove', { method: 'POST', cache: 'no-store', headers: { accept: 'application/json', 'content-type': 'application/json' }, body: JSON.stringify(ask), signal: abort.signal })
    const body: unknown = await res.json()
    const why = body && typeof body === 'object' ? (body as { error?: unknown }).error : null
    return res.ok ? parseProve(body) : typeof why === 'string' && why.trim() ? { error: why.trim() } : null
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/** The layout the page was built with, for when /nodes.json can't be had. */
function builtLayout(): unknown {
  return typeof __BUILD_LAYOUT__ === 'undefined' ? null : __BUILD_LAYOUT__
}

export function boardSource(wsUrl: string): Source {
  return {
    kind: 'board',
    feed: feedFrom('ws', wsTransport(wsUrl)),
    layout: async () => parseLayout(await getJson('/nodes.json')) ?? parseLayout(builtLayout()),
    chain: async () => parseChain(await getJson('/chain')),
    tail: async (n) => parseTail(await getJson(`/chain/tail?n=${n}`)),
    prove: (ask) => postProve(ask ?? {}),
    lastAsk: async () => parseAsk(await getJson('/ask/last')),
    privacy: async () => parsePrivacy(await getJson('/privacy')),
  }
}

/** A source that plays a simulated kit: `at(t)` gives everything at t ms into the scene. */
export interface Scene {
  layout: Layout
  state: EngineState | null
  chain: ChainInfo | null
  tail: TailRecord[] | null
  ask: AskLast | null
  privacy: Privacy | null
  prove: ProveResult | null
}

/** The simulated board's answer to a prove-it ask: the record asked for is the one altered in the copy. */
export function mockProve(scene: Scene, ask?: { n: number; seq: number } | null): ProveResult | null {
  return scene.prove && ask ? { ...scene.prove, altered_seq: ask.seq, first_bad_seq: ask.seq } : scene.prove
}

export function mockSource(at: (tMs: number) => Scene, kind: Source['kind'] = 'mock', clock: () => number = () => performance.now()): Source {
  const t0 = clock()
  const now = () => at(clock() - t0)
  const transport: Transport = {
    start(deliver, setConnected) {
      setConnected(true)
      const tick = () => {
        const s = now().state
        if (s) deliver({ v: 2, type: 'state', src: 'sim', seq: Math.round(s.t / 250), ...s })
      }
      tick()
      setInterval(tick, 250)
    },
    send() {},
  }
  return {
    kind,
    feed: feedFrom('mock', transport),
    layout: async () => now().layout,
    chain: async () => now().chain,
    tail: async (n) => now().tail?.slice(-n) ?? null,
    prove: async (ask) => mockProve(now(), ask),
    lastAsk: async () => now().ask,
    privacy: async () => now().privacy,
  }
}
