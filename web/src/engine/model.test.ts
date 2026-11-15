import { describe, expect, it } from 'vitest'
import { ENGINE_SCENES, MOCK_LAYOUT, engineScene, fakeHash, records, sceneAt, witnessIds } from './mock'
import { ago, blocks, boardId, count, deviceViews, hash8, headlines, heardNow, kindWord, parseAsk, parseChain, parseLayout, parsePrivacy, parseProve, parseTail, proveWords, seenHeads, span, timings, watchLine, type ChainInfo } from './model'

const HASH = 'a3f09c21'.repeat(8)
const chain = (over: Partial<ChainInfo> = {}): ChainInfo => ({
  head: { seq: 1187, hash: HASH }, records: 1187, since_t: null, verified: true, last_verify_t: 86_000, first_bad_seq: null,
  witnesses: [{ node: 'pi5', last_seq: 1185, last_t: 98_000, sig_ok: true, silent: false }, { node: 'pi5b', last_seq: 1185, last_t: 98_000, sig_ok: true, silent: false }],
  last_verify_checked: 600, last_verify_ms: 3, ...over,
})

describe('what the board says, read carefully', () => {
  it('reads GET /chain as the witness wording has it, and refuses what is not one', () => {
    const c = parseChain({ head: { seq: 1187, hash: HASH.toUpperCase() }, records: 1187, since_t: 5, verified: true, last_verify_t: 9, first_bad_seq: null, witnesses: [{ node: 'pi5', last_seq: 1185, last_t: 8, sig_ok: true, silent: false }, { nope: 1 }] })!
    expect(c.head).toEqual({ seq: 1187, hash: HASH })
    expect(c.witnesses).toEqual([{ node: 'pi5', last_seq: 1185, last_t: 8, sig_ok: true, silent: false }])
    expect(c.last_verify_ms).toBeNull() // not in the wording: shown only when the board sends it
    expect(parseChain({ ...c, verified: 'checking' })!.verified).toBe('checking')
    for (const bad of [null, {}, { head: { seq: 1, hash: 'xyz' }, records: 1, verified: true }, { head: { seq: -1, hash: HASH }, records: 1, verified: true }, { head: { seq: 1, hash: HASH }, records: 1, verified: 'yes' }]) {
      expect(parseChain(bad)).toBeNull()
    }
  })

  it('reads a tail of records, a prove result, an answer and the privacy meter', () => {
    const tail = parseTail([{ seq: 3, t: 1, kind: 'witness', hash8: 'aabbccdd', node: 'pi5', for_seq: 2 }, { seq: 2, kind: 'summary', hash: HASH }, { seq: 'x' }])!
    expect(tail.map((r) => r.seq)).toEqual([2, 3]) // oldest first, and the row that is not a record left out
    expect(tail[1]).toMatchObject({ kind: 'witness', node: 'pi5', for_seq: 2, hash: 'aabbccdd' })
    expect(parseTail({ records: [{ seq: 1, kind: 'summary', hash: HASH }] })).toHaveLength(1)
    expect(parseTail('no')).toBeNull()
    expect(parseProve({ ok: false, altered_seq: 1187, first_bad_seq: 1187, ms: 3 })).toEqual({ ok: false, altered_seq: 1187, first_bad_seq: 1187, ms: 3 })
    expect(parseProve({ ok: false })).toBeNull()
    const ask = parseAsk({ answer: ' Nobody was here. ', steps: [{ tool: 'presence', ms: 12, rows: 60 }, 'x'], cites: [1180, 'a', 1185], chain_ok: true })!
    expect(ask).toEqual({ question: null, answer: 'Nobody was here.', steps: [{ tool: 'presence', ms: 12, rows: 60 }], cites: [1180, 1185], chain_ok: true })
    expect(parseAsk({ answer: '' })).toBeNull()
    expect(parsePrivacy({ ok: true, images: 0, bytes_out: 0, since_t: 1, t: 2 })).toEqual({ images: 0, bytes_out: 0 })
    expect(parsePrivacy({ ok: false, why: 'privacy meter is not running' })).toBeNull()
  })

  it('reads the devices and lines from the layout file', () => {
    expect(parseLayout({ nodes: [{ id: 'unoq', name: ' Board ', device: 'unoq', roles: ['receiver', 3] }], links: [] })).toEqual({ nodes: [{ id: 'unoq', name: 'Board', device: 'unoq', roles: ['receiver'] }], links: [] })
    expect(parseLayout({ nodes: [] , links: [] })).toBeNull()
    expect(parseLayout({ nodes: 'none' })).toBeNull()
  })
})

describe('words and numbers', () => {
  it('says counts, hashes, ages and kinds the way a person reads them', () => {
    expect(count(1187)).toBe('1,187')
    expect(hash8(HASH)).toBe('a3f0 9c21')
    expect([0, 400, 2000, 89_000, 150_000, 3 * 3600_000].map(ago)).toEqual(['now', 'now', '2 s ago', '89 s ago', '3 min ago', '3 h ago'])
    expect(span(12_000)).toBe('12 s')
    expect(kindWord('summary')).toBe('second')
    expect(kindWord('witness_silent')).toBe('witness silent')
    expect(kindWord('something_new')).toBe('something new') // an unknown kind is shown as it is
  })

  it('gives the three numbers, and blanks with no board', () => {
    const [head, witnesses, verified] = headlines(chain(), MOCK_LAYOUT, 100_000)
    expect(head).toMatchObject({ value: '#1,187', note: 'a3f0 9c21 · 1,187 sealed', fault: false })
    expect(witnesses).toMatchObject({ value: '2 of 2', note: 'Pi A and Pi B', fault: false })
    expect(verified).toMatchObject({ value: '14 s ago', note: '600 records checked in 3 ms', fault: false })
    expect(headlines(null, null, 0).map((h) => h.value)).toEqual(['__', '__', '__'])
    // What the board did not measure is not written: no "records checked" without the numbers.
    expect(headlines(chain({ last_verify_checked: null, last_verify_ms: null }), MOCK_LAYOUT, 100_000)[2].note).toBe('every record follows the one before')
  })

  it('says a silent witness and a chain that does not verify in words, in the fault colour', () => {
    const silent = chain({ witnesses: [chain().witnesses[0], { node: 'pi5b', last_seq: 1170, last_t: 80_000, sig_ok: true, silent: true }] })
    expect(headlines(silent, MOCK_LAYOUT, 100_000)[1]).toMatchObject({ value: '1 of 2', note: 'Pi B silent: the chain goes on', fault: true })
    expect(headlines(chain({ verified: false, first_bad_seq: 1150 }), MOCK_LAYOUT, 100_000)[2]).toMatchObject({ value: 'No', note: 'the chain breaks at record #1,150', fault: true })
    expect(headlines(chain({ verified: 'checking', last_verify_t: null }), MOCK_LAYOUT, 0)[2].value).toBe('Checking')
  })

  it('reports the prove-it check as the board gave it', () => {
    expect(proveWords({ ok: false, altered_seq: 1187, first_bad_seq: 1187, ms: 3 })).toEqual({ words: 'Record #1,187 was altered in a copy: the chain breaks here. The real record is untouched. Checked in 3 ms.', fault: false })
    expect(proveWords({ ok: false, altered_seq: 1187, first_bad_seq: 1188, ms: null }).words).toBe('Record #1,187 was altered in a copy: the chain breaks at record #1,188. The real record is untouched.')
    // A copy that still verifies after being altered would be a real fault, and is said as one.
    expect(proveWords({ ok: true, altered_seq: 1187, first_bad_seq: 1187, ms: 3 })).toMatchObject({ fault: true })
  })

  it('never writes a zero it has not measured', () => {
    expect(watchLine(null, null)).toEqual(['Camera: __', 'No microphone on any device', 'privacy meter not answering'])
    expect(watchLine({ t: 0, cam: 'off' }, { images: 0, bytes_out: 0 })).toEqual(['0 cameras', 'No microphone on any device', '0 images stored', '0 bytes out'])
    expect(watchLine({ t: 0, cam: 'on' }, null, true)).toEqual(['Camera ON', 'No microphone on any device', 'privacy meter: simulated, nothing measured'])
    expect(timings({ t: 0, model: { ms_per_decision: null, train_s: null } }, null)).toEqual([])
    expect(timings({ t: 0, model: { ms_per_decision: 3.1, train_s: null }, narration: { gen_ms: 410 } }, { question: null, answer: 'x', steps: [{ tool: 'a', ms: 3, rows: 1 }, { tool: 'b', ms: 12, rows: 1 }], cites: [], chain_ok: true })).toEqual(['Decision 3.1 ms', 'Sentence 410 ms', 'Answer 15 ms'])
  })
})

describe('the devices', () => {
  const links = MOCK_LAYOUT.links.map((l) => ({ id: l.id, rate_hz: l.kind === 'wifi' ? 25 : 6, status: 'ok' }))

  it('puts the board first and says what each does, hears and signed', () => {
    expect(boardId(MOCK_LAYOUT, chain().witnesses)).toBe('unoq')
    const [board, a, b] = deviceViews(MOCK_LAYOUT, { t: 100_000, links }, chain(), 100_000, new Map())
    expect(board).toMatchObject({ name: 'Board', does: 'Senses, decides, seals the record', hz: 37, heard: true, witness: null })
    expect(board.hears).toEqual([{ from: 'Pi A', radio: 'Wi-Fi', hz: 25 }, { from: 'Pi A', radio: 'Bluetooth', hz: 6 }, { from: 'Pi B', radio: 'Bluetooth', hz: 6 }])
    expect(a).toMatchObject({ name: 'Pi A', does: 'The Wi-Fi of the room, and a witness', hz: 6, heard: true })
    expect(a.witness).toEqual({ seq: 1185, ago: '2 s ago', ok: true, silent: false, quiet: null })
    expect(b).toMatchObject({ name: 'Pi B', does: 'Listens across the gap, and a witness', hz: 31 })
  })

  it('says how long a device has not been heard and how long a witness has not signed; the rest goes on', () => {
    const off = links.map((l) => (l.id.includes('pi5b') ? { ...l, rate_hz: 0, status: 'stale' } : l))
    expect([...heardNow(MOCK_LAYOUT, off)].sort()).toEqual(['pi5', 'unoq'])
    const silent = chain({ witnesses: [chain().witnesses[0], { node: 'pi5b', last_seq: 1170, last_t: 88_000, sig_ok: true, silent: true }] })
    const [board, a, b] = deviceViews(MOCK_LAYOUT, { t: 100_000, links: off }, silent, 100_000, new Map([['pi5b', 88_000]]))
    expect(b).toMatchObject({ heard: false, quiet: 'not heard for 12 s' })
    expect(b.witness).toMatchObject({ silent: true, quiet: 'has not signed for 12 s' })
    expect(a.heard).toBe(true)
    expect(board.hz).toBe(31) // its own two lines from Pi A still read
    expect(deviceViews(MOCK_LAYOUT, null, null, 0, new Map()).map((d) => d.quiet)).toEqual(['not heard yet', 'not heard yet', 'not heard yet'])
  })
})

describe('the strip of records', () => {
  const tail = parseTail([
    { seq: 10, kind: 'summary', hash: fakeHash(10) }, { seq: 11, kind: 'witness', hash: fakeHash(11), node: 'pi5', for_seq: 10 },
    { seq: 12, kind: 'witness', hash: fakeHash(12), node: 'pi5b', for_seq: 10 }, { seq: 13, kind: 'summary', hash: fakeHash(13) }, { seq: 14, kind: 'enter', hash: fakeHash(14) },
  ])!

  it('draws each record as a block and each signature as a mark on the record it vouches for', () => {
    const list = blocks(tail, MOCK_LAYOUT, [13], null)
    expect(list.map((b) => [b.seq, b.word, b.signed, b.cited])).toEqual([
      [10, 'second', ['Pi A', 'Pi B'], false], [11, 'Pi A signed', [], false], [12, 'Pi B signed', [], false], [13, 'second', [], true], [14, 'entered', [], false],
    ])
    expect(list[0].hash).toBe(fakeHash(10).slice(0, 6))
    expect(blocks(tail, MOCK_LAYOUT, [], null, 2).map((b) => b.seq)).toEqual([13, 14]) // the newest, at most n
  })

  it('marks every record from the break onward when the chain does not verify', () => {
    expect(blocks(tail, MOCK_LAYOUT, [], 12).map((b) => b.bad)).toEqual([false, false, true, true, true])
  })

  it('keeps the heads it has seen when the board gives no list, and starts again when the log does', () => {
    let seen = seenHeads([], { seq: 5, hash: HASH })
    seen = seenHeads(seen, { seq: 5, hash: HASH })
    seen = seenHeads(seen, { seq: 6, hash: HASH })
    expect(seen.map((h) => h.seq)).toEqual([5, 6])
    expect(seenHeads(seen, { seq: 2, hash: HASH }).map((h) => h.seq)).toEqual([2])
    expect(seenHeads(seen, null)).toEqual(seen)
  })
})

describe('the simulated kit', () => {
  it('knows its scenes, and plays "running" for a name it does not know', () => {
    expect([...ENGINE_SCENES]).toEqual(['running', 'silent', 'broken', 'answer', 'none'])
    expect(engineScene('silent')).toBe('silent')
    expect(engineScene('whatever')).toBe('running')
    expect(engineScene(null)).toBe('running')
  })

  it('seals one record a second with no gaps, each witness signing the head every 5 s', () => {
    const all = records('running', MOCK_LAYOUT, 30)
    expect(all.map((r) => r.seq)).toEqual(all.map((_, i) => all[0].seq + i))
    expect(all.filter((r) => r.kind === 'summary')).toHaveLength(31)
    const signed = all.filter((r) => r.kind === 'witness')
    expect(signed).toHaveLength(14) // 7 rounds, two witnesses
    for (const s of signed) expect(all.find((r) => r.seq === s.for_seq)!.kind).toBe('summary')
    expect(witnessIds(MOCK_LAYOUT)).toEqual(['pi5', 'pi5b'])
    // The same record number always has the same made-up hash, 64 hex characters.
    expect(fakeHash(1187)).toMatch(/^[0-9a-f]{64}$/)
    expect(fakeHash(1187)).toBe(fakeHash(1187))
    expect(fakeHash(1187)).not.toBe(fakeHash(1188))
  })

  it('running: both witnesses sign, the chain verifies, and nothing measured is claimed', () => {
    const s = sceneAt('running', 20_000)
    expect(parseChain(s.chain)).toEqual(s.chain) // the mock speaks the board's own shape
    expect(s.chain!.verified).toBe(true)
    expect(s.chain!.witnesses.map((w) => w.silent)).toEqual([false, false])
    expect(s.chain!.head.seq).toBe(s.tail!.at(-1)!.seq)
    expect(s.state!.chain!.seq).toBe(s.chain!.head.seq)
    expect(s.privacy).toBeNull()
    expect(sceneAt('running', 1000).chain!.verified).toBe('checking') // the first check has not run yet
  })

  it('silent: one witness stops, is recorded as silent once, the chain goes on, and it comes back', () => {
    const before = sceneAt('silent', 6000).chain!
    const during = sceneAt('silent', 27_000)
    const after = sceneAt('silent', 36_000)
    expect(before.witnesses.map((w) => w.silent)).toEqual([false, false])
    expect(during.chain!.witnesses.map((w) => w.silent)).toEqual([false, true])
    expect(during.chain!.head.seq).toBeGreaterThan(before.head.seq + 15) // the chain went on
    expect(during.state!.links!.filter((l) => l.id.includes('pi5b')).every((l) => l.rate_hz === 0)).toBe(true)
    const kinds = records('silent', MOCK_LAYOUT, 36).filter((r) => r.kind.startsWith('witness_')).map((r) => r.kind)
    expect(kinds).toEqual(['witness_silent', 'witness_back'])
    expect(after.chain!.witnesses.map((w) => w.silent)).toEqual([false, false])
    expect(after.chain!.verified).toBe(true)
  })

  it('broken: the chain does not verify and names the record; answer: cites records in the strip; none: nothing', () => {
    const broken = sceneAt('broken', 10_000).chain!
    expect(broken.verified).toBe(false)
    expect(broken.first_bad_seq).toBe(broken.head.seq - 6)
    const answer = sceneAt('answer', 20_000)
    expect(answer.ask!.chain_ok).toBe(true)
    for (const c of answer.ask!.cites) expect(answer.tail!.some((r) => r.seq === c)).toBe(true)
    expect(parseAsk(answer.ask)).toEqual(answer.ask)
    // Every second of every scene can be drawn: nothing throws while there is little to show yet.
    for (const scene of ENGINE_SCENES) for (let t = 0; t < 50_000; t += 500) expect(() => sceneAt(scene, t)).not.toThrow()
    const prove = sceneAt('running', 20_000).prove!
    expect(prove).toMatchObject({ ok: false })
    expect(prove.first_bad_seq).toBe(prove.altered_seq)
    expect(sceneAt('none', 5000)).toMatchObject({ state: null, chain: null, tail: null, ask: null, privacy: null, prove: null })
  })

  it('plays on whatever devices the layout file has: only the computers sign', () => {
    const five: typeof MOCK_LAYOUT = { nodes: [...MOCK_LAYOUT.nodes, { id: 'east', name: 'East beacon', device: 'esp32', roles: ['beacon'] }], links: [...MOCK_LAYOUT.links, { id: 'east>unoq:ble', tx: 'east', rx: 'unoq', kind: 'ble' }] }
    expect(witnessIds(five)).toEqual(['pi5', 'pi5b'])
    expect(sceneAt('running', 12_000, five).state!.links).toHaveLength(7)
  })
})
