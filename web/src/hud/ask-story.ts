import type { AskResponse } from './ask-client'

const measured = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n >= 0
export const recordNumbers = (value: unknown) => Array.isArray(value) ? [...new Set(value.filter(n => measured(n) && Number.isSafeInteger(n) && n > 0))] : []
export function storyView(reply: AskResponse) {
  if (!Array.isArray(reply.steps) || !reply.steps.length) return null
  const warning = reply.chain_ok === false ? reply.answer.match(/^.*?[.!?](?:\s|$)/s)?.[0].trim() || reply.answer : ''
  const rows = reply.rows.filter(row => typeof row.text === 'string' && row.text.trim()).map(row => ({
    text: String(row.text),
    time: typeof row.at === 'string' && row.at.trim() ? row.at : measured(row.t) && row.t <= 8640000000000000 ? `${new Date(row.t).toISOString().slice(11,19)} UTC` : '__',
    cites: recordNumbers(row.cites),
  }))
  return {warning, rows, fallback: rows.length ? '' : reply.answer.slice(warning.length).trim(),
    steps: reply.steps.filter(step => step && typeof step.tool === 'string').map(step => `${step.tool} · ${measured(step.ms) ? step.ms : '__'} ms · ${measured(step.rows) ? step.rows : '__'} rows`),
    cites: recordNumbers(reply.cites)}
}
export function renderStory(root: HTMLElement, reply: AskResponse) {
  root.replaceChildren()
  const value = storyView(reply)
  root.hidden = !value
  if (!value) return false
  const add = (tag: string, text: string, className = '') => {
    const el = document.createElement(tag); el.textContent = text; el.className = className; root.append(el); return el
  }
  if (value.warning) { const warning = add('p',value.warning,'story-warning'); warning.setAttribute('role','alert') }
  if (value.fallback) add('p',value.fallback,'story-answer')
  const list = add('ol','','story-timeline')
  for (const row of value.rows) {
    const item = document.createElement('li'), time = document.createElement('time'), text = document.createElement('p')
    time.textContent = row.time; text.textContent = row.text; item.append(time,text)
    list.append(item)
  }
  if (value.steps.length) {
    add('h3','On the board')
    const steps = add('ol','','story-steps')
    for (const text of value.steps) { const item=document.createElement('li'); item.textContent=text; steps.append(item) }
  }
  if (value.cites.length) add('p',`Cited records: ${value.cites.join(', ')}`,'story-cites')
  return true
}
