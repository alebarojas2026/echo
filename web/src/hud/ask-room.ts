import { examples, mockAskClient, type AskClient } from './ask-client'
import { changingText } from './changing-text'
import type { Proof } from './state'
import { fetchProof } from '../room/hud-host'
import './ask-room.css'

export function mountAskRoom(host: HTMLElement, client: AskClient = mockAskClient) {
  const trigger = document.createElement('button')
  trigger.type = 'button'
  trigger.className = 'ask-trigger'
  trigger.textContent = 'Ask the room'
  host.append(trigger)
  const dialog = document.createElement('dialog')
  dialog.className = 'ask-room'
  dialog.setAttribute('aria-labelledby', 'ask-title')
  dialog.innerHTML = `<header><h2 id="ask-title">Ask the room</h2><button type="button" class="ask-close">Close</button></header>
    <p class="ask-mode"></p>
    <form><label for="room-question">Your question</label><div class="ask-input"><input id="room-question" name="question" required maxlength="500" autocomplete="off"><button class="ask-submit">Ask</button></div></form>
    <details class="ask-example-list" open><summary>Example questions</summary><div class="ask-examples" aria-label="Example questions"></div></details>
    <p role="status" data-testid="ask-progress" hidden>Reading the room records…</p>
    <section class="ask-result" aria-live="polite" hidden><p data-testid="ask-answer"></p><div class="ask-evidence" hidden><h3>Records behind this answer</h3><ul data-testid="ask-rows"></ul></div><p data-testid="ask-time"></p><p data-testid="ask-privacy"></p></section>
    <p role="alert" data-testid="ask-error" hidden></p>`
  document.body.append(dialog)
  const input = dialog.querySelector<HTMLInputElement>('input')!
  const form = dialog.querySelector('form')!
  const submit = dialog.querySelector<HTMLButtonElement>('.ask-submit')!
  const progress = dialog.querySelector<HTMLElement>('[data-testid="ask-progress"]')!
  const result = dialog.querySelector<HTMLElement>('.ask-result')!
  const answer = dialog.querySelector<HTMLElement>('[data-testid="ask-answer"]')!
  const answerText = changingText(answer)
  const rows = dialog.querySelector('[data-testid="ask-rows"]')!
  const evidence = dialog.querySelector<HTMLElement>('.ask-evidence')!
  const timing = dialog.querySelector('[data-testid="ask-time"]')!
  const privacy = dialog.querySelector('[data-testid="ask-privacy"]')!
  const error = dialog.querySelector<HTMLElement>('[data-testid="ask-error"]')!
  dialog.querySelector('.ask-mode')!.textContent = client.mode === 'mock' ? 'Mock response · board connection pending' : 'Answers from records on the board'
  let controller: AbortController | undefined
  let generation = 0
  let previousFocus: HTMLElement | null = null
  const idle = () => { progress.hidden = true; submit.disabled = false; form.removeAttribute('aria-busy') }
  const close = () => {
    generation++
    controller?.abort()
    idle()
    dialog.close()
    input.blur()
    if (previousFocus && previousFocus !== document.body) previousFocus.focus()
    else trigger.focus()
  }
  const open = () => {
    if (!dialog.open) { previousFocus = document.activeElement as HTMLElement; dialog.showModal() }
    input.focus()
  }
  trigger.onclick = open
  dialog.querySelector<HTMLButtonElement>('.ask-close')!.onclick = close
  dialog.addEventListener('cancel', event => { event.preventDefault(); close() })
  const key = (event: KeyboardEvent) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || (event.target as HTMLElement)?.closest('input, textarea, select, [contenteditable]')) return
    event.preventDefault()
    open()
  }
  document.addEventListener('keydown', key)
  for (const question of examples) {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = question
    button.onclick = () => { input.value = question; form.requestSubmit() }
    dialog.querySelector('.ask-examples')!.append(button)
  }
  form.onsubmit = async event => {
    event.preventDefault()
    const question = input.value.trim()
    if (!question) { input.focus(); return }
    controller?.abort()
    controller = new AbortController()
    const current = ++generation
    dialog.querySelector('details')!.open = false
    progress.hidden = false
    result.hidden = true
    error.hidden = true
    submit.disabled = true
    form.setAttribute('aria-busy', 'true')
    try {
      const response = await client.ask(question, controller.signal)
      if (current !== generation) return
      answerText.set(response.answer)
      rows.replaceChildren()
      for (const row of response.rows) {
        const item = document.createElement('li')
        item.textContent = Object.entries(row).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`).join(' · ')
        rows.append(item)
      }
      evidence.hidden = response.rows.length === 0
      timing.textContent = `${client.mode === 'mock' ? 'Mock response time' : 'Answer time'}: ${response.ms != null && Number.isFinite(response.ms) && response.ms >= 0 ? response.ms : '__'} ms`
      privacy.textContent = client.mode === 'mock' ? 'Mock response · __ bytes out' : 'Answered on the board · __ bytes out'
      result.hidden = false
      if (client.mode === 'board') {
        void fetchProof().then(proof => {
          if (current !== generation) return
          const bytes = (proof as Proof | null)?.bytes_out
          privacy.textContent = `Answered on the board · ${bytes != null && Number.isFinite(bytes) && bytes >= 0 ? bytes : '__'} bytes out`
        })
      }
    } catch (reason) {
      if (current !== generation) return
      error.textContent = 'The room could not answer. Try the question again.'
      error.hidden = false
    } finally { if (current === generation) idle() }
  }
  return () => { generation++; controller?.abort(); document.removeEventListener('keydown', key); answerText.dispose(); dialog.remove(); trigger.remove() }
}
