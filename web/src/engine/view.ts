import { blocks, count, deviceViews, headlines, hearsLines, proveAsk, proveWords, seenHeads, timings, toolWord, watchLine, type AskLast, type Block, type ChainInfo, type EngineState, type Layout, type Privacy, type ProveResult, type TailRecord } from './model'
import { engineState, type Source } from './source'

// The engine room: a second screen beside the judge's, showing the machinery as it runs. Three devices, the
// sealed record growing, the witnesses signing it, the last check, the prove-it control and the detective's last
// answer. An operator's screen: nothing under 20 px, and the three numbers at the top read from across a desk.
// Everything shown is what the board reported; a part the board has no answer for stays off or says so.

const CHAIN_EVERY_MS = 1500
const SLOW_EVERY_MS = 2500
const PROVE_SHOWN_MS = 10_000
const TICK_MS = 900
const STRIP_BLOCKS = 20

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

function blockEl(b: Block, extra = ''): HTMLLIElement {
  const li = el('li', `eng-block${b.cited ? ' eng-block--cited' : ''}${b.bad ? ' eng-block--bad' : ''}${extra}`)
  li.dataset.seq = String(b.seq)
  const top = el('span', 'eng-block-top')
  top.append(el('b', '', `#${count(b.seq)}`))
  // One mark for each witness that signed this record's hash.
  if (b.signed.length) {
    const marks = el('span', 'eng-block-signed')
    marks.title = `Signed by ${b.signed.join(' and ')}`
    marks.setAttribute('aria-label', marks.title)
    b.signed.forEach(() => marks.append(el('i')))
    top.append(marks)
  }
  li.append(top, el('span', 'eng-block-kind', b.word), el('span', 'eng-block-hash', b.hash))
  return li
}

export function mountEngine(host: HTMLElement, source: Source): () => void {
  host.classList.add('eng')
  host.replaceChildren()

  // ---- top: what this is, where the data comes from, and what is not watching
  const top = el('header', 'eng-top')
  const title = el('h1', '', 'Echo')
  title.append(el('span', '', 'Engine room'))
  const badge = el('p', 'eng-source')
  badge.dataset.testid = 'engine-source'
  const watch = el('p', 'eng-watch')
  watch.dataset.testid = 'engine-watch'
  top.append(title, badge, watch)

  // ---- the three numbers
  const heads = el('section', 'eng-heads')
  const headEls = [0, 1, 2].map(() => {
    const box = el('div', 'eng-head')
    const label = el('p', 'eng-head-label')
    const value = el('p', 'eng-head-value')
    const note = el('p', 'eng-head-note')
    box.append(label, value, note)
    heads.append(box)
    return { box, label, value, note }
  })
  headEls[0].value.dataset.testid = 'engine-head'
  headEls[1].value.dataset.testid = 'engine-witnesses'
  headEls[2].value.dataset.testid = 'engine-verified'

  // ---- the devices
  const devices = el('section', 'eng-devices')
  devices.dataset.testid = 'engine-devices'

  // ---- the sealed record
  const chainBox = el('section', 'eng-chain')
  const chainTitle = el('h2', '', 'The sealed record')
  const chainNote = el('p', 'eng-note')
  const strip = el('ol', 'eng-strip')
  strip.dataset.testid = 'engine-strip'
  chainBox.append(chainTitle, chainNote, strip)

  // ---- prove it, and the last answer
  const bottom = el('section', 'eng-bottom')
  const proveBox = el('div', 'eng-prove')
  const proveButton = el('button', 'eng-button', 'Prove it')
  proveButton.type = 'button'
  proveButton.dataset.testid = 'engine-prove'
  const proveSay = el('p', 'eng-prove-say')
  proveSay.dataset.testid = 'engine-prove-result'
  proveSay.setAttribute('role', 'status')
  const copy = el('ol', 'eng-strip eng-strip--copy')
  copy.hidden = true
  const PROVE_NOTE = 'The board changes one record in a copy and checks the copy. The real record is never touched.'
  const proveNote = el('p', 'eng-note', PROVE_NOTE)
  const proveRow = el('div', 'eng-prove-row')
  proveRow.append(proveButton, proveSay)
  proveBox.append(el('h2', '', 'Can the record be edited?'), proveNote, copy, proveRow)

  const askBox = el('div', 'eng-ask')
  askBox.dataset.testid = 'engine-ask'
  const askTitle = el('h2', '', 'The last answer')
  const askAnswer = el('p', 'eng-ask-answer')
  const askSteps = el('ol', 'eng-steps')
  const askCites = el('p', 'eng-note')
  const timing = el('p', 'eng-note eng-timing')
  askBox.append(askTitle, askAnswer, askSteps, askCites, timing)
  bottom.append(proveBox, askBox)

  host.append(top, heads, devices, chainBox, bottom)

  // ---- what the board last said
  let layout: Layout | null = null
  let chain: ChainInfo | null = null
  let tail: TailRecord[] | null = null
  let ask: AskLast | null = null
  let privacy: Privacy | null = null
  let seen: { seq: number; hash: string }[] = []
  let proved: { result: ProveResult | null; refused: string | null; at: number } | null = null
  let proving = false
  const heardAt = new Map<string, number>()
  const signedSeq = new Map<string, number | null>()
  const deviceEls = new Map<string, { card: HTMLElement; rate: HTMLElement; hears: HTMLElement; heard: HTMLElement; signed: HTMLElement; tick: HTMLElement }>()
  let lastStripHead = 0
  let disposed = false

  /** The board's clock now: the latest state's own time, carried forward; this machine's clock with no state. */
  const boardNow = (): number => {
    const snap = source.feed.current()
    const state = engineState(source.feed)
    return state && snap.receivedAt !== null ? state.t + (performance.now() - snap.receivedAt) : Date.now()
  }

  function drawDevices(state: EngineState | null, now: number) {
    if (!layout) {
      if (!devices.childElementCount) devices.append(el('p', 'eng-note', 'Waiting for the layout file.'))
      return
    }
    const views = deviceViews(layout, state, chain, now, heardAt)
    if (deviceEls.size !== views.length || views.some((v) => !deviceEls.has(v.id))) {
      devices.replaceChildren()
      deviceEls.clear()
      for (const v of views) {
        const card = el('article', 'eng-device')
        card.dataset.node = v.id
        const rate = el('p', 'eng-rate')
        const hears = el('ul', 'eng-hears')
        const heard = el('p', 'eng-heard')
        const signedRow = el('p', 'eng-signed')
        const tick = el('i', 'eng-tick')
        tick.setAttribute('aria-hidden', 'true')
        const signed = el('span')
        signedRow.append(tick, signed)
        const head = el('div', 'eng-device-head')
        head.append(el('h2', '', v.name), heard)
        card.append(head, el('p', 'eng-does', v.does), rate, hears, signedRow)
        devices.append(card)
        deviceEls.set(v.id, { card, rate, hears, heard, signed, tick })
      }
    }
    for (const v of views) {
      const d = deviceEls.get(v.id)!
      const quiet = !v.heard || !!v.witness?.silent
      d.card.dataset.state = quiet ? 'quiet' : 'ok'
      say(d.rate, v.hz === null ? (v.hears.length ? '__ readings a second' : 'Sends its signal; hears no line') : `${v.hz} readings a second`)
      const lines = hearsLines(v.hears)
      if (d.hears.dataset.lines !== lines.join('|')) {
        d.hears.dataset.lines = lines.join('|')
        d.hears.replaceChildren(...lines.map((l) => el('li', '', l)))
      }
      say(d.heard, v.heard ? 'Heard now' : (v.quiet ?? 'not heard'))
      const w = v.witness
      say(d.signed, v.board ? 'Seals every record' : !w ? (chain ? 'Not enrolled as a witness' : 'No word from the board on its signatures') : w.silent ? `Silent witness: ${w.quiet}. The chain goes on.` : w.seq === null ? 'No signature yet' : `Signed record #${count(w.seq)}${w.ago ? `, ${w.ago}` : ''}${w.ok ? '' : ' (signature did NOT check)'}`)
      d.tick.hidden = !w
      // A small tick each time a new signature arrives: lit, then back to rest. Once per signature, never a loop.
      if (w && signedSeq.get(v.id) !== w.seq) {
        if (signedSeq.has(v.id) && w.seq !== null) {
          d.tick.classList.add('eng-tick--on')
          setTimeout(() => d.tick.classList.remove('eng-tick--on'), TICK_MS)
        }
        signedSeq.set(v.id, w.seq)
      }
    }
  }

  function drawStrip() {
    const cites = ask?.cites ?? []
    let list: Block[]
    if (tail?.length) {
      list = blocks(tail, layout, cites, chain?.verified === false ? chain.first_bad_seq : null, STRIP_BLOCKS)
      say(chainNote, 'One block for each record, newest on the right. Each carries the hash of the one before it. A dot is a witness signature.')
    } else {
      // The board gave no list of records: the heads this page has seen go by, with no kinds (it was not told).
      list = seen.slice(-STRIP_BLOCKS).map((h) => ({ seq: h.seq, word: 'head', hash: h.hash.slice(0, 6), signed: [], cited: cites.includes(h.seq), bad: false }))
      say(chainNote, chain ? 'The board gives no list of records here: these are the heads this screen has seen go by.' : 'No sealed record to show: the board has not answered.')
    }
    const key = list.map((b) => `${b.seq}${b.cited ? 'c' : ''}${b.bad ? 'x' : ''}${b.signed.join('')}`).join(',')
    if (strip.dataset.key === key) return
    strip.dataset.key = key
    const head = list.at(-1)?.seq ?? 0
    const added = lastStripHead && head > lastStripHead ? list.filter((b) => b.seq > lastStripHead).length : 0
    lastStripHead = head
    // The row sits against the strip's right edge (newest record there). New records push it left: it starts
    // shifted right by the new blocks' width and slides home.
    const row = el('div', 'eng-strip-row')
    row.append(...list.map((x) => blockEl(x)))
    strip.replaceChildren(row)
    const first = row.firstElementChild as HTMLElement | null
    if (added && first && typeof first.getBoundingClientRect === 'function') {
      const step = first.getBoundingClientRect().width + 8
      row.style.transition = 'none'
      row.style.transform = `translateX(${Math.min(added, 4) * step}px)`
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          row.style.transition = ''
          row.style.transform = ''
        }),
      )
    }
  }

  function drawProve(now: number) {
    if (proved && now - proved.at >= PROVE_SHOWN_MS) proved = null
    proveButton.disabled = proving
    if (proving) return say(proveSay, 'Asking the board…')
    if (!proved) {
      proveSay.classList.remove('eng-fault')
      copy.hidden = true
      say(proveNote, PROVE_NOTE)
      return say(proveSay, '')
    }
    if (!proved.result) {
      proveSay.classList.add('eng-fault')
      copy.hidden = true
      say(proveNote, PROVE_NOTE)
      return say(proveSay, proved.refused ? `The board says: ${proved.refused}. Nothing was checked.` : 'The board did not answer, so nothing was checked.')
    }
    const { words, fault } = proveWords(proved.result)
    proveSay.classList.toggle('eng-fault', fault)
    say(proveSay, words)
    // The copy, drawn apart from the real strip: the altered record in the fault colour, and nothing after it holds.
    const r = proved.result
    const around = (tail ?? []).filter((x) => x.seq >= r.altered_seq - 3 && x.seq <= r.altered_seq + 4)
    const key = `${r.altered_seq}:${around.length}`
    if (copy.dataset.key !== key) {
      copy.dataset.key = key
      copy.replaceChildren(...blocks(around, layout, [], r.ok ? null : r.first_bad_seq, 8).map((b) => blockEl(b, b.seq === r.altered_seq ? ' eng-block--altered' : '')))
    }
    copy.hidden = around.length === 0
    // While a result shows, the note names what is drawn under it: the copy, never the real record.
    say(proveNote, copy.hidden ? PROVE_NOTE : `A copy of the record, with #${count(r.altered_seq)} changed:`)
  }

  function drawAsk(state: EngineState | null) {
    askBox.dataset.state = ask ? 'answer' : 'none'
    if (!ask) {
      say(askAnswer, 'No question has been answered yet.')
      askSteps.replaceChildren()
      say(askCites, '')
    } else {
      say(askAnswer, ask.answer)
      const steps = ask.steps.map((s, i) => `${i + 1}. ${toolWord(s.tool)}${s.rows === null ? '' : ` · ${count(s.rows)} records`}${s.ms === null ? '' : ` · ${s.ms} ms`}`)
      if (askSteps.dataset.key !== steps.join('|')) {
        askSteps.dataset.key = steps.join('|')
        askSteps.replaceChildren(...steps.map((s) => el('li', '', s)))
      }
      const cited = ask.cites.length ? `Cites record${ask.cites.length > 1 ? 's' : ''} ${ask.cites.map((c) => `#${count(c)}`).join(', ')}` : 'Cites no record'
      const ok = ask.chain_ok === null ? '' : ask.chain_ok ? ' · the chain verified over them' : ' · the chain did NOT verify over them'
      askCites.classList.toggle('eng-fault', ask.chain_ok === false)
      say(askCites, cited + ok)
    }
    say(timing, timings(state, ask).join(' · '))
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
    say(badge, source.kind === 'mock' ? 'Simulated' : noBoard ? 'No board' : state ? 'Live' : 'No data')
    say(watch, watchLine(state, privacy, source.kind === 'mock').join(' · '))
    headlines(chain, layout, now).forEach((h, i) => {
      say(headEls[i].label, h.label)
      say(headEls[i].value, h.value)
      say(headEls[i].note, h.note)
      headEls[i].box.classList.toggle('eng-fault', h.fault)
    })
    drawDevices(state, now)
    drawStrip()
    drawProve(performance.now())
    drawAsk(state)
  }

  async function prove() {
    if (proving) return
    proving = true
    draw()
    // The record to alter is one on the strip, so the copy can be drawn beside it.
    const answer = await source.prove(proveAsk(tail))
    proving = false
    proved = { result: answer && 'error' in answer ? null : answer, refused: answer && 'error' in answer ? answer.error : null, at: performance.now() }
    draw()
  }
  proveButton.addEventListener('click', () => void prove())

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
    timers.forEach(clearInterval)
  }
}
