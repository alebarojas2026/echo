const { test, expect } = require('@playwright/test')
require('./layout-fixture.cjs')

// The walk-up card on a page that draws no frames (a background tab, a covered window, a laptop lid half shut):
// animations stand still and timers are held back. The card must still follow the board, from the times in its
// states alone. Here the page's clock is stopped for the whole test, so no timer and no animation frame ever
// runs, every animation is paused where it starts, and the page reports itself hidden.
test('the card follows the board clock while no frame is drawn and no timer runs', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    const hidden = () => window.__noFrames === true
    Object.defineProperty(Document.prototype, 'visibilityState', { configurable: true, get: () => (hidden() ? 'hidden' : 'visible') })
    Object.defineProperty(Document.prototype, 'hidden', { configurable: true, get: hidden })
    const animate = Element.prototype.animate
    Element.prototype.animate = function (...args) {
      const animation = animate.apply(this, args)
      if (hidden()) animation.pause()
      return animation
    }
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
  await page.goto('/tests/arrival-harness.html')
  await expect.poll(() => page.evaluate(() => !!window.arrival)).toBe(true)
  const title = page.getByTestId('arrival-title'), card = page.locator('.hud-arrival')
  await page.clock.runFor(300)
  await expect(title).toHaveText('Nobody is here.')
  // From here on the clock never runs again.
  await page.evaluate(() => { window.__noFrames = true; document.dispatchEvent(new Event('visibilitychange')) })
  const T0 = 1_800_000_000_000
  /** Ten states a second of board time, as the brain sends them; `empty` lists the ticks that say nobody. */
  const feed = (fromMs, toMs, empty = []) => page.evaluate(([from, to, gaps, t0]) => {
    for (let ms = from; ms <= to; ms += 100) window.arrival.update(gaps.includes(ms) ? 'empty' : 'still', { t: t0 + ms })
  }, [fromMs, toMs, empty, T0])
  await page.evaluate(t => window.arrival.update('empty', { t }), T0 - 100)
  await page.evaluate(() => window.arrival.event('enter', 'one'))
  // One tick that says nobody inside the first second and a half does not start the count again.
  await feed(0, 1400, [700])
  await expect(title).toHaveText('Nobody is here.')
  expect(await page.evaluate(() => document.documentElement.dataset.hudArrival)).toBe('waiting')
  await feed(1500, 1600)
  await expect(title).toHaveText('Found you.')
  await expect(card).toBeVisible()
  await feed(1700, 2800)
  expect(await page.evaluate(() => document.documentElement.dataset.hudArrival)).toBe('found')
  await feed(2900, 4500)
  await expect(card).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.dataset.hudArrival)).toBe('closed')
  await expect(page.getByTestId('judge-headline')).toHaveText(/^(Someone is here, standing still|Still )/)
  expect(await page.locator('#hud').evaluate(el => el.inert)).toBe(false)

  // Between judges: the card is back, and somebody who leaves before "Found you." is not found.
  await page.evaluate(t => { window.arrival.update('empty', { t }); window.arrival.event('reset') }, T0 + 10_000)
  await expect(card).toBeVisible()
  await expect(title).toHaveText('Nobody is here.')
  await feed(10_100, 11_000)
  await page.evaluate(t => { for (let ms = 11_100; ms <= 11_600; ms += 100) window.arrival.update('empty', { t: t + ms }) }, T0)
  await feed(11_700, 12_900)
  await expect(title).toHaveText('Nobody is here.')
  await feed(13_000, 13_300)
  await expect(title).toHaveText('Found you.')

  // A page that got nothing for a while (asleep, or the tab frozen) and then one state: the card is where the
  // board's clock says, at once.
  await page.evaluate(t => window.arrival.update('still', { t }), T0 + 60_000)
  await expect(card).toBeHidden()
  expect(errors).toEqual([])
})
