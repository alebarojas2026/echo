const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const layout = require('../../radio/layouts/gate.json')
const shots = process.env.HUD_SCREENSHOTS

// A walk straight through the one spot (the board's passed_by event) on the hall-first judge's page: the words
// come up and go again, and the figure walks on, off and through. With no such event the page is as it was.
const chain = { seq: 4127, verified: true, witnesses_ok: 2, witnesses: 2 }
const NOBODY = ['Nobody is here.', 'Step up to the desk.']
const WALKED = ['Someone walked through.', 'Nobody stopped.']

async function open(page, { reduced = false } = {}) {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/nodes.json', (route) => route.fulfill({ json: layout }))
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.emulateMedia({ reducedMotion: reduced ? 'reduce' : 'no-preference' })
  await page.goto('/tests/arrival-harness.html')
  await expect(page.locator('#room')).toHaveAttribute('data-scan', 'loaded', { timeout: 30000 })
  await expect(page.locator('html')).toHaveAttribute('data-judge-layout', 'hall')
  // The board's states, ten a second, and every value the figure's motion takes, as it takes it.
  await page.evaluate((chain) => {
    window.__say = { name: 'empty', over: { chain } }
    setInterval(() => window.arrival.update(window.__say.name, window.__say.over), 100)
    window.__moves = []
    const room = document.getElementById('room')
    new MutationObserver(() => {
      const move = room.dataset.ghostMove ?? ''
      if (window.__moves.at(-1) !== move) window.__moves.push(move)
    }).observe(room, { attributes: true, attributeFilter: ['data-ghost-move'] })
  }, chain)
  return errors
}
const say = (page, name, over = {}) => page.evaluate(({ name, over, chain }) => { window.__say = { name, over: { chain, ...over } } }, { name, over, chain })
const event = (page, kind, info = {}) => page.evaluate(({ kind, info }) => window.arrival.event(kind, undefined, info), { kind, info })
const moves = (page) => page.evaluate(() => window.__moves.splice(0).filter(Boolean))
/** The words on the screen: the walk-up card's while it is up, the page's own otherwise. */
const words = async (page) => {
  const card = await page.locator('.hud-arrival').isVisible()
  return card
    ? [await page.getByTestId('arrival-title').innerText(), await page.getByTestId('arrival-detail').innerText()]
    : [await page.getByTestId('judge-headline').innerText(), await page.getByTestId('judge-detail').innerText()]
}
const room = (page) => page.locator('#room')
const shot = async (page, name) => {
  if (!shots) return
  fs.mkdirSync(shots, { recursive: true })
  await page.screenshot({ path: path.join(shots, `${name}.png`) })
}
/** Someone steps in and stays until the walk-up card has gone and the camera is down at the spot. */
async function firstArrival(page) {
  await say(page, 'still')
  await expect(room(page)).toHaveAttribute('data-view', 'square', { timeout: 30000 })
  await expect(page.locator('.hud-arrival')).toBeHidden()
  await expect.poll(() => words(page)).toContain('Someone is here.')
}

test('a walk through: the words come up for about 3 s and go, on the walk-up card and on the page', async ({ page }) => {
  const errors = await open(page)
  // With no event the page says what it always said, however long it waits.
  await page.waitForTimeout(1500)
  expect(await words(page)).toEqual(NOBODY)
  expect(await moves(page)).toEqual([])

  // On the walk-up card (nobody has stepped in yet).
  await event(page, 'passed_by', { zone: 1 })
  await expect.poll(() => words(page)).toEqual(WALKED)
  await expect(page.locator('.hud-arrival')).not.toHaveAttribute('data-tone', 'fault') // calm: it is not an alert
  await shot(page, 'walk-through-card')
  await page.waitForTimeout(2000)
  expect(await words(page)).toEqual(WALKED) // still up at 2 s
  await expect.poll(() => words(page), { timeout: 3000 }).toEqual(NOBODY) // and gone soon after 3 s
  expect(await moves(page)).toEqual(['through'])

  // On the page itself, after somebody has been and gone.
  await firstArrival(page)
  await say(page, 'empty')
  await expect.poll(() => words(page)).toEqual(NOBODY)
  await expect(room(page)).toHaveAttribute('data-ghost', '')
  await page.waitForTimeout(1200)
  await moves(page)
  const before = Date.now()
  await event(page, 'passed_by', { zone: 1 })
  await expect.poll(() => words(page)).toEqual(WALKED)
  await expect(page.locator('.judge-moment')).toHaveAttribute('data-tone', '')
  await shot(page, 'walk-through-page')
  await expect.poll(() => words(page), { timeout: 6000, intervals: [100] }).toEqual(NOBODY)
  const shown = Date.now() - before
  expect(shown).toBeGreaterThan(2500)
  expect(shown).toBeLessThan(5000) // about 3 s, with room for a slow machine
  expect(await moves(page)).toEqual(['through'])
  // No side and no count is ever said.
  expect(WALKED.join(' ')).not.toMatch(/left|right|\d/)

  // Somebody who steps in while the words are up is said at once: the walk-through never covers a person.
  await event(page, 'passed_by', { zone: 1 })
  await expect.poll(() => words(page)).toEqual(WALKED)
  await say(page, 'still')
  await expect.poll(() => words(page)).toContain('Someone is here.')
  await page.waitForTimeout(3500)
  expect((await words(page))[0]).toBe('Someone is here.')

  // A reset ends it.
  await say(page, 'empty')
  await expect.poll(() => words(page)).toEqual(NOBODY)
  await event(page, 'passed_by', { zone: 1 })
  await expect.poll(() => words(page)).toEqual(WALKED)
  await event(page, 'reset')
  await expect.poll(() => words(page), { timeout: 1500 }).toEqual(NOBODY)
  expect(errors).toEqual([])
})

test('armed, a passer-by is said as it was: one calm line over "Armed.", never "walked through"', async ({ page }) => {
  const errors = await open(page)
  await say(page, 'empty', { armed: true })
  await expect.poll(() => words(page)).toEqual(['Armed.', 'This space should be empty.'])
  await event(page, 'passed_by', { zone: 1 })
  await expect(page.getByTestId('arrival-passed')).toHaveText('Someone passed by at the desk')
  expect(await words(page)).toEqual(['Armed.', 'This space should be empty.'])
  await page.waitForTimeout(600)
  expect(await words(page)).toEqual(['Armed.', 'This space should be empty.'])
  expect(errors).toEqual([])
})

test('the figure walks on, walks off and ends where the board says', async ({ page }) => {
  const errors = await open(page)
  await firstArrival(page)
  await page.waitForTimeout(1200)
  await moves(page)
  // Leaving: it walks off and is gone.
  await say(page, 'empty')
  await expect(room(page)).toHaveAttribute('data-ghost-move', 'off', { timeout: 3000 })
  await expect(room(page)).toHaveAttribute('data-ghost-move', '', { timeout: 3000 })
  await expect(room(page)).toHaveAttribute('data-ghost', '')
  expect(await moves(page)).toEqual(['off'])
  // Arriving: it walks on and stands on the spot.
  await say(page, 'still')
  await expect(room(page)).toHaveAttribute('data-ghost-move', 'on', { timeout: 3000 })
  await shot(page, 'walk-on')
  await expect(room(page)).toHaveAttribute('data-ghost-move', '', { timeout: 3000 })
  await expect(room(page)).toHaveAttribute('data-ghost', '1')
  expect(await moves(page)).toEqual(['on'])
  await page.waitForTimeout(1800) // a stand, not a walk through (a leaving within 1.5 s would be one)
  // A step aside and back: an arrival during the walk off turns it round, and it ends standing there.
  await say(page, 'empty')
  await expect(room(page)).toHaveAttribute('data-ghost-move', 'off', { timeout: 3000 })
  await say(page, 'still')
  await expect(room(page)).toHaveAttribute('data-ghost-move', 'on', { timeout: 3000 })
  await expect(room(page)).toHaveAttribute('data-ghost-move', '', { timeout: 3000 })
  await expect(room(page)).toHaveAttribute('data-ghost', '1')
  expect(await moves(page)).toEqual(['off', 'on'])
  // A passer-by while somebody stands there draws nothing more: there is one figure.
  await event(page, 'passed_by', { zone: 1 })
  await page.waitForTimeout(500)
  expect(await moves(page)).toEqual([])
  expect(errors).toEqual([])
})

test('a slow crossing (enter, then exit 0.8 s later) is a walk through too: the words, and the figure goes on across', async ({ page }) => {
  const errors = await open(page)
  await firstArrival(page)
  await say(page, 'empty')
  await expect.poll(() => words(page)).toEqual(NOBODY)
  await expect(room(page)).toHaveAttribute('data-ghost', '')
  await page.waitForTimeout(1200)
  await moves(page)
  await say(page, 'still')
  await expect.poll(() => words(page)).toContain('Someone is here.')
  await page.waitForTimeout(800)
  await say(page, 'empty')
  const before = Date.now()
  await expect.poll(() => words(page)).toEqual(WALKED)
  await expect(page.locator('.judge-moment')).toHaveAttribute('data-tone', '')
  await expect.poll(() => words(page), { timeout: 6000, intervals: [100] }).toEqual(NOBODY)
  expect(Date.now() - before).toBeGreaterThan(2500)
  expect(Date.now() - before).toBeLessThan(5000) // about 3 s, with room for a slow machine
  // It walked on, and then on across and off the far side: it did not go back the way it came.
  expect(await moves(page)).toEqual(['on', 'through'])
  await expect(room(page)).toHaveAttribute('data-ghost', '')
  expect(errors).toEqual([])
})

test('a stand of 10 s reads "Someone is here." throughout, and leaving after it is a leaving', async ({ page }) => {
  const errors = await open(page)
  await firstArrival(page)
  await say(page, 'empty')
  await expect.poll(() => words(page)).toEqual(NOBODY)
  await page.waitForTimeout(1200)
  await moves(page)
  await say(page, 'still')
  await expect.poll(() => words(page)).toContain('Someone is here.')
  const heard = new Set()
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(500)
    heard.add((await words(page))[0])
  }
  expect([...heard]).toEqual(['Someone is here.'])
  await say(page, 'empty')
  await expect.poll(() => words(page)).toEqual(NOBODY)
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(500)
    expect(await words(page)).toEqual(NOBODY) // never "walked through" after a real stand
  }
  expect(await moves(page)).toEqual(['on', 'off'])
  expect(errors).toEqual([])
})

test('with motion turned down the figure fades in place, as before', async ({ page }) => {
  const errors = await open(page, { reduced: true })
  await firstArrival(page)
  await say(page, 'empty')
  await expect(room(page)).toHaveAttribute('data-ghost', '', { timeout: 3000 })
  await page.waitForTimeout(800)
  await say(page, 'still')
  await expect(room(page)).toHaveAttribute('data-ghost', '1', { timeout: 3000 })
  await page.waitForTimeout(800)
  await say(page, 'empty')
  await expect(room(page)).toHaveAttribute('data-ghost', '', { timeout: 3000 })
  await event(page, 'passed_by', { zone: 1 })
  await expect.poll(() => words(page)).toEqual(WALKED) // the words are said; the figure does not cross
  await page.waitForTimeout(1200)
  expect(await moves(page)).toEqual([])
  expect(errors).toEqual([])
})

test('a tab that was hidden shows the figure where the board says at once, with no walk left to watch', async ({ page }) => {
  const errors = await open(page)
  await firstArrival(page)
  await say(page, 'empty')
  await expect(room(page)).toHaveAttribute('data-ghost', '', { timeout: 3000 })
  await page.waitForTimeout(1200)
  await moves(page)
  const show = (state) => page.evaluate((state) => {
    Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
  }, state)
  // Somebody steps in while the tab is in the background: no walk on is started, then or when it comes back.
  await show('hidden')
  await say(page, 'still')
  await expect(room(page)).toHaveAttribute('data-ghost', '1', { timeout: 3000 })
  await show('visible')
  await page.waitForTimeout(1800) // long enough to be a stand
  expect(await moves(page)).toEqual([])
  // A walk off that the tab was hidden in the middle of is over when it comes back.
  await say(page, 'empty')
  await expect(room(page)).toHaveAttribute('data-ghost-move', 'off', { timeout: 3000 })
  await show('hidden')
  await show('visible')
  await expect(room(page)).toHaveAttribute('data-ghost-move', '', { timeout: 300 })
  await expect(room(page)).toHaveAttribute('data-ghost', '')
  expect(errors).toEqual([])
})
