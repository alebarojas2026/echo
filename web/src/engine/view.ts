import { alarmWords, blocks, checkedWords, citesWords, count, deviceViews, headlines, hearsLines, proveAsk, proveWords, recordRows, rowWords, ROW_BLOCKS, seenHeads, signedWords, timings, toolWord, watchLine, type AskLast, type Block, type ChainInfo, type DeviceView, type EngineState, type Layout, type Privacy, type ProveResult, type TailRecord } from './model'
import { engineState, type Source } from './source'

// The engine room: a second screen beside the judge's. One picture: the sealed record as a row of blocks, the
// newest solid at the right under its own number; one row per witness with a mark under each record it signed;
// one button that proves the record cannot be edited. Everything shown is what the board reported; a part the
// board has no answer for stays off or says so. The plumbing (readings a second, hashes, timings) is the
// operator's: it shows with the O key or ?op=1.

const CHAIN_EVERY_MS = 1500
const SLOW_EVERY_MS = 2500
const PROVE_SHOWN_MS = 10_000
const SHIFT_MS = 200
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'
const PROVE_NOTE = 'Changes one record in a copy and shows where the chain breaks.'

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text) node.textContent = text
  return node
}

/** Sets text only when it changed, so nothing on the page is rewritten for the same words. */
function say(node: HTMLElement, text: string) {
  if (node.textContent !== text) node.textContent = text
}

function tagged<T extends HTMLElement>(node: T, testid: string): T {
  node.dataset.testid = testid
  return node
}

interface RowEls { name: HTMLElement; row: HTMLElement; words: HTMLElement | null }

export function mountEngine(host: HTMLElement, source: Source): () => void {
  host.classList.add('eng')
  host.replaceChildren()

  // ---- top: what this is. The source is said only when it is not the live board.
  const top = el('header', 'eng-top')
  const title = el('h1', '', 'Echo')
  title.append(el('span', '', 'Engine room'))
  const badge = tagged(el('p', 'eng-source'), 'engine-source')
  top.append(title, badge)

  // ---- the heading and the newest record's number
  const head = el('section', 'eng-head')
  const headLeft = el('div', 'eng-head-words')
  const heading = tagged(el('h2'), 'engine-title')
  const alarm = tagged(el('p', 'eng-alarm'), 'engine-alarm')
  alarm.setAttribute('role', 'status')
  headLeft.append(heading, alarm)
  const number = tagged(el('p', 'eng-count'), 'engine-head')
  head.append(headLeft, number)

  // ---- the picture: the board's row of records, a row per witness, the copy while a prove-it result shows
  const record = tagged(el('section', 'eng-record'), 'engine-record')
  const signed = tagged(el('p', 'eng-signed'), 'engine-signed')
  const copyName = el('span', 'eng-name', 'A copy')
  const copyRow = tagged(el('div', 'eng-row eng-row--chain eng-row--copy'), 'engine-copy')
  const copyTrack = el('div', 'eng-track')
  copyTrack.append(copyRow)
  const copy = el('div', 'eng-copy')
  copy.append(copyName, copyTrack)

  // ---- the last answer to "What happened?": it takes the space under the picture when there is one
  const askBox = tagged(el('section', 'eng-ask'), 'engine-ask')
  const askQuestion = el('p', 'eng-ask-question')
  const askAnswer = el('p', 'eng-ask-answer')
  const askSteps = el('ol', 'eng-steps')
  const askCites = el('p', 'eng-ask-cites')
  askBox.append(askQuestion, askAnswer, askSteps, askCites)

  // ---- the foot: the one control, its one sentence, and the last check
  const foot = el('footer', 'eng-foot')
  const proveButton = tagged(el('button', 'eng-prove', 'PROVE IT'), 'engine-prove')
  proveButton.type = 'button'
  const proveNote = el('p', 'eng-prove-note', PROVE_NOTE)
  const proveSay = tagged(el('p', 'eng-prove-say'), 'engine-prove-result')
  proveSay.setAttribute('role', 'status')
  const proveWordsBox = el('div', 'eng-prove-words')
  proveWordsBox.append(proveNote, proveSay)
  const checked = tagged(el('p', 'eng-checked'), 'engine-verified')
  foot.append(proveButton, proveWordsBox, checked)

  // ---- the operator's lines (O key, or ?op=1): the plumbing a judge does not need
  const op = tagged(el('aside', 'eng-op'), 'engine-op')
  op.hidden = !new URLSearchParams(location.search).has('op')

  host.append(top, head, record, askBox, foot, op)

  // ---- what the board last said
  let layout: Layout | null = null
  let chain: ChainInfo | null = null
  let tail: TailRecord[] | null = null
  let ask: AskLast | null = null
  let privacy: Privacy | null = null
  let seen: { seq: number; hash: string }[] = []
  let proved: { result: ProveResult | null; refused: string | null; at: number; head: number; staged: boolean } | null = null
  let proving = false
  const heardAt = new Map<string, number>()
  const rowEls = new Map<string, RowEls>()
  let rowsKey = ''
  let lastHead = 0
  let disposed = false

  /** The board's clock now: the latest state's own time, carried forward; this machine's clock with no state. */
  const boardNow = (): number => {
    const snap = source.feed.current()
    const state = engineState(source.feed)
    return state && snap.receivedAt !== null ? state.t + (performance.now() - snap.receivedAt) : Date.now()
  }

  /** The devices as rows. With no layout file, the board and whoever the board says signs, by their ids. */
  function views(state: EngineState | null, now: number): DeviceView[] {
    const known: Layout = layout ?? { nodes: [{ id: 'board', name: 'Board', device: 'unoq', roles: [] }, ...(chain?.witnesses ?? []).map((w) => ({ id: w.node, name: w.node, device: 'pi', roles: [] }))], links: [] }
    return recordRows(deviceViews(known, state, chain, now, heardAt), known)
  }

  /** The records the row shows, oldest first: the board's list, or with none the heads this page saw go by. */
  function shown(): Block[] {
    const cites = ask?.cites ?? []
    if (tail?.length) return blocks(tail, layout, cites, chain?.verified === false ? chain.first_bad_seq : null, ROW_BLOCKS)
    return seen.slice(-ROW_BLOCKS).map((h) => ({ seq: h.seq, word: 'head', hash: h.hash.slice(0, 6), signed: [], cited: cites.includes(h.seq), bad: false }))
  }

  function drawRecord(rows: DeviceView[], list: Block[], result: ProveResult | null) {
    // The rows themselves are built once per set of devices; each second only their blocks and marks change.
    const ids = rows.map((v) => v.id).join('|')
    if (ids !== rowsKey) {
      rowsKey = ids
      rowEls.clear()
      record.replaceChildren()
      for (const v of rows) {
        const name = el('span', 'eng-name', v.name)
        const row = el('div', v.board ? 'eng-row eng-row--chain' : 'eng-row')
        const track = el('div', 'eng-track')
        track.dataset.node = v.id
        const words = v.board ? null : el('p', 'eng-row-words')
        track.append(row, ...(words ? [words] : []))
        record.append(name, track)
        rowEls.set(v.id, { name, row, words })
      }
      record.append(signed, copy)
      lastHead = 0
    }
    for (const v of rows) {
      const r = rowEls.get(v.id)!
      const w = rowWords(v, chain)
      // The fault colour goes on the name and the words that say the fault, and on nothing else.
      r.name.classList.toggle('eng-fault', !!w?.fault)
      if (r.words) {
        r.words.classList.toggle('eng-fault', !!w?.fault)
        say(r.words, w?.words ?? '')
        r.row.parentElement!.dataset.state = w?.fault ? 'quiet' : 'ok'
      }
    }

    const newest = list.at(-1)?.seq ?? 0
    const key = list.map((b) => `${b.seq}${b.cited ? 'c' : ''}${b.bad ? 'x' : ''}${b.signed.join('')}`).join(',')
    const copyKey = result ? `${result.altered_seq}:${result.first_bad_seq}:${result.ok}` : ''
    if (record.dataset.key === key && record.dataset.copy === copyKey) return
    const moved = record.dataset.key !== key
    record.dataset.key = key
    record.dataset.copy = copyKey
    record.dataset.full = list.length >= ROW_BLOCKS ? 'yes' : 'no'
    const added = lastHead && newest > lastHead ? list.filter((b) => b.seq > lastHead).length : 0
    const fresh = (b: Block) => (added && b.seq > lastHead ? ' eng-in' : '')

    for (const v of rows) {
      const r = rowEls.get(v.id)!
      r.row.replaceChildren(
        ...list.map((b, i) => {
          const last = i === list.length - 1
          if (v.board) {
            const block = el('i', `eng-block${last ? ' eng-block--head' : ''}${b.cited ? ' eng-block--cited' : ''}${b.bad ? ' eng-block--bad' : ''}${fresh(b)}`)
            block.dataset.seq = String(b.seq)
            return block
          }
          // One mark under each record this witness signed.
          const mark = el('span', `eng-mark${last ? ' eng-mark--head' : ''}`)
          if (b.signed.includes(v.name)) mark.append(el('i', fresh(b).trim()))
          return mark
        }),
      )
    }

    // The copy, under the real row and never in it: the same records, the altered one and all after it broken.
    copy.hidden = !result
    if (result && proved) {
      const stage = !proved.staged
      proved.staged = true
      let nth = 0
      copyRow.replaceChildren(
        ...list.map((b, i) => {
          const last = i === list.length - 1
          if (b.seq > proved!.head) return el('span', `eng-gap${last ? ' eng-gap--head' : ''}`)
          const bad = !result.ok && b.seq >= result.first_bad_seq
          const block = el('i', `eng-block${last ? ' eng-block--head' : ''}${bad ? ' eng-block--bad' : ''}${b.seq === result.altered_seq ? ' eng-block--altered' : ''}`)
          block.dataset.seq = String(b.seq)
          // The one staged moment: the break runs left to right, once.
          if (bad && stage) {
            block.classList.add('eng-break')
            block.style.animationDelay = `${nth++ * 30}ms`
          }
          return block
        }),
      )
    } else copyRow.replaceChildren()

    lastHead = newest
    // New records push the rows one place left: they start shifted and slide home, the three rows as one.
    if (moved && added && typeof copyRow.animate === 'function' && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const pitch = (rowEls.get(rows[0]?.id ?? '')?.row.firstElementChild as HTMLElement | null)?.getBoundingClientRect().width ?? 0
      const gap = parseFloat(getComputedStyle(document.documentElement).fontSize) * 1.5
      const from = `translateX(${Math.min(added, 4) * (pitch + gap)}px)`
      for (const r of [...rowEls.values()].map((x) => x.row).concat(copyRow)) r.animate([{ transform: from }, { transform: 'none' }], { duration: SHIFT_MS, easing: EASE_OUT })
    }
  }

  function drawProve(now: number) {
    if (proved && now - proved.at >= PROVE_SHOWN_MS) proved = null
    proveButton.disabled = proving
    const result = proving ? '' : !proved ? '' : proved.result ? proveWords(proved.result).words : proved.refused ? `The board says: ${proved.refused}. Nothing was checked.` : 'The board did not answer, so nothing was checked.'
    const words = proving ? 'Asking the board…' : result
    proveSay.classList.toggle('eng-fault', !proving && !!proved && (!proved.result || proveWords(proved.result).fault))
    say(proveSay, words)
    // One sentence beside the button at a time: what it does, or what it found.
    proveNote.hidden = !!words
    proveSay.hidden = !words
  }

  function drawAsk(showing: boolean) {
    askBox.dataset.state = ask ? 'answer' : 'none'
    askBox.hidden = !ask
    askBox.dataset.covered = showing ? 'no' : 'yes'
    if (!ask) {
      askAnswer.removeAttribute('title')
      askSteps.replaceChildren()
      delete askSteps.dataset.key
      return
    }
    say(askQuestion, ask.question ?? 'The last answer')
    say(askAnswer, ask.answer)
    askAnswer.title = ask.answer // the screen shows the first lines of a long story; the whole of it is here
    const steps = ask.steps.map((s, i) => `${i + 1}. ${toolWord(s.tool)}${s.rows === null ? '' : ` · ${count(s.rows)} ${s.rows === 1 ? 'record' : 'records'}`}${s.ms === null ? '' : ` · ${s.ms} ms`}`)
    if (askSteps.dataset.key !== steps.join('|')) {
      askSteps.dataset.key = steps.join('|')
      askSteps.replaceChildren(...steps.map((s) => el('li', '', s)))
    }
    const ok = ask.chain_ok === null ? '' : ask.chain_ok ? ' · the chain verified over them' : ' · the chain did NOT verify over them'
    askCites.classList.toggle('eng-fault', ask.chain_ok === false)
    say(askCites, citesWords(ask.cites) + ok)
  }

  function drawOp(state: EngineState | null, all: DeviceView[], now: number) {
    if (op.hidden) return
    const lines = [
      watchLine(state, privacy, source.kind === 'mock').join(' · '),
      ...headlines(chain, layout, now).map((h) => `${h.label}: ${h.value} · ${h.note}`),
      ...all.map((v) => `${v.name}: ${v.heard ? 'heard now' : (v.quiet ?? 'not heard')} · ${v.hz === null ? (v.hears.length ? '__ readings a second' : 'hears no line') : `${v.hz} readings a second`}${v.hears.length ? ` (${hearsLines(v.hears).join('; ')})` : ''}`),
      timings(state, ask).join(' · '),
    ].filter(Boolean)
    if (op.dataset.key === lines.join('\n')) return
    op.dataset.key = lines.join('\n')
    op.replaceChildren(...lines.map((l) => el('p', '', l)))
  }

  function draw() {
    if (disposed) return
    const snap = source.feed.current()
    const state = snap.stale ? null : engineState(source.feed)
    const now = boardNow()
    if (state && layout) {
      const links = state.links ?? []
      const live = new Set(links.filter((l) => (l.rate_hz ?? 0) > 0 && l.status !== 'stale' && l.status !== 'blind').map((l) => l.id))
      for (const l of layout.links) {
        if (live.has(l.id)) {
          heardAt.set(l.tx, state.t)
          heardAt.set(l.rx, state.t)
        }
      }
    }
    const noBoard = !state && !chain
    host.dataset.board = noBoard ? 'none' : 'here'
    host.dataset.chain = chain?.verified === false ? 'broken' : 'ok'
    const sourceWord = source.kind === 'mock' ? 'Simulated' : noBoard ? 'No board' : state ? 'Live' : 'No data'
    say(badge, sourceWord)
    badge.dataset.source = sourceWord === 'Live' ? 'live' : 'other'

    const a = alarmWords(chain, !!state)
    say(heading, a.title)
    heading.classList.toggle('eng-fault', a.fault && !!chain)
    say(alarm, a.words)
    alarm.classList.toggle('eng-fault', a.fault)
    say(number, chain ? count(chain.head.seq) : '__')
    number.dataset.known = chain ? 'yes' : 'no'
    number.setAttribute('aria-label', chain ? `Record ${count(chain.head.seq)} is the newest` : 'No record to show')

    drawProve(performance.now())
    const all = views(state, now)
    drawRecord(all, shown(), proved?.result ?? null)
    say(signed, signedWords(chain, layout, now))
    // While the copy is on the screen the answer waits: one thing under the picture at a time.
    drawAsk(!proved?.result)
    const c = checkedWords(chain, now)
    say(checked, c.words)
    checked.classList.toggle('eng-fault', c.fault)
    drawOp(state, layout ? deviceViews(layout, state, chain, now, heardAt) : all, now)
  }

  async function prove() {
    if (proving) return
    proving = true
    draw()
    // The record to alter is one on the row, so the copy can be drawn under it.
    const answer = await source.prove(proveAsk(tail))
    proving = false
    proved = { result: answer && 'error' in answer ? null : answer, refused: answer && 'error' in answer ? answer.error : null, at: performance.now(), head: chain?.head.seq ?? 0, staged: false }
    draw()
  }
  proveButton.addEventListener('click', () => void prove())

  const onKey = (e: KeyboardEvent) => {
    if (e.key.toLowerCase() !== 'o' || e.ctrlKey || e.metaKey || e.altKey) return
    op.hidden = !op.hidden
    delete op.dataset.key
    draw()
  }
  addEventListener('keydown', onKey)

  async function pollChain() {
    const [c, t] = await Promise.all([source.chain(), source.tail(40)])
    chain = c
    tail = t
    seen = seenHeads(seen, c?.head ?? null)
    draw()
  }
  async function pollSlow() {
    if (!layout) layout = await source.layout()
    ;[ask, privacy] = await Promise.all([source.lastAsk(), source.privacy()])
    draw()
  }

  const off = source.feed.subscribe(() => draw())
  const timers = [setInterval(() => void pollChain(), CHAIN_EVERY_MS), setInterval(() => void pollSlow(), SLOW_EVERY_MS), setInterval(draw, 1000)]
  void pollSlow().then(pollChain)
  draw()
  return () => {
    disposed = true
    off()
    removeEventListener('keydown', onKey)
    timers.forEach(clearInterval)
  }
}
