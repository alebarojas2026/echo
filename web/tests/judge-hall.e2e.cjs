const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const layout = require('../../radio/layouts/gate.json')
const shots = process.env.HUD_SCREENSHOTS

// The hall-first judge's page (the one-spot layout): the hall is the whole screen, the state is one headline and
// one line under it, and there is one control. Checked on the real page with the hall model loaded.
const quiet = { state: 'none', zone: null, still_s: 0, limit_s: 10 }
const chain = { seq: 4127, verified: true, witnesses_ok: 2, witnesses: 2 }

/** What a judge can read now: every shown piece of text with its size and its box. */
const read = (page) => page.evaluate(() => {
  const out = []
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  for (let node = walk.nextNode(); node; node = walk.nextNode()) {
    const text = node.textContent.trim(), el = node.parentElement
    if (!text || !el || el.closest('script,style,.hud-operator,.visually-hidden,dialog:not([open])')) continue
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue
    const range = document.createRange()
    range.selectNodeContents(node)
    const box = range.getBoundingClientRect()
    if (!box.width || !box.height) continue
    out.push({ text, px: parseFloat(getComputedStyle(el).fontSize), left: box.left, top: box.top, right: box.right, bottom: box.bottom })
  }
  return out
})

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`one headline, one line and one control on the hall at ${width}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.route('**/nodes.json', (route) => route.fulfill({ json: layout }))
    await page.setViewportSize({ width, height })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/tests/arrival-harness.html')
    await expect(page.locator('#room')).toHaveAttribute('data-scan', 'loaded', { timeout: 30000 })
    await expect(page.locator('html')).toHaveAttribute('data-judge-layout', 'hall')

    const send = (name, over = {}, motion = null, stale = false) => page.evaluate(({ name, over, motion, stale }) => {
      const pred = window.arrival.peek(name).pred
      window.arrival.update(name, motion ? { ...over, pred: { ...pred, motion } } : over, stale)
    }, { name, over, motion, stale })
    const hold = async (...args) => { for (let i = 0; i < 4; i++) { await send(...args); await page.waitForTimeout(250) } }
    /** The words on the screen: the walk-up card's while it is up, the page's own otherwise. Never both. */
    const words = async () => {
      const card = await page.locator('.hud-arrival').isVisible()
      await expect(page.getByTestId('judge-headline')).toBeVisible({ visible: !card })
      return card
        ? [await page.getByTestId('arrival-title').innerText(), await page.getByTestId('arrival-detail').innerText()]
        : [await page.getByTestId('judge-headline').innerText(), await page.getByTestId('judge-detail').innerText()]
    }
    const sound = async (name) => {
      const texts = await read(page)
      const said = texts.map((t) => t.text)
      // Nothing a judge reads is under 28 px, and nothing runs off the screen.
      expect(texts.filter((t) => t.px < 28), `${name}: text under 28 px`).toEqual([])
      expect(texts.filter((t) => t.left < 0 || t.top < 0 || t.right > width + 0.5 || t.bottom > height + 0.5), `${name}: text off the screen`).toEqual([])
      expect(await page.evaluate(() => [document.documentElement.scrollWidth <= innerWidth, document.documentElement.scrollHeight <= innerHeight])).toEqual([true, true])
      // The hall is the whole screen, and the picture carries no stickers.
      const room = await page.locator('#room').boundingBox()
      expect([room.x, room.width]).toEqual([0, width])
      for (const gone of ['Board', 'Pi A', 'Pi B', 'At the desk', 'Our desk', 'Person', 'Object', 'Visitor 0', 'Hall model built from a scan, not by the board.']) expect(said, `${name}: "${gone}"`).not.toContain(gone)
      // One control, bottom right, clear of the words.
      const asks = page.locator('[data-testid="what-happened"]:visible, [data-testid="arrival-what-happened"]:visible')
      await expect(asks).toHaveCount(1)
      await expect(asks).toHaveText('What happened?')
      await expect(asks).toBeInViewport({ ratio: 1 })
      const ask = await asks.boundingBox()
      expect(ask.height).toBeGreaterThanOrEqual(64)
      expect(ask.x + ask.width).toBeGreaterThan(width - 80)
      const headline = texts.filter((t) => t.px >= 56)
      expect(headline.length, `${name}: one headline`).toBe(1)
      // Room to spare for a face a tenth wider than this one.
      expect(headline[0].left + (headline[0].right - headline[0].left) * 1.1).toBeLessThan(ask.x - 24)
      for (const kept of ['Echo', 'No camera. No microphone.', 'Sealed record · verified · 2 witnesses']) expect(said, `${name}: "${kept}"`).toContain(kept)
      if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: path.join(shots, `${width}-${name}.png`) }) }
    }

    // The walk-up card, before anybody has stood on the spot.
    await hold('empty', { chain })
    expect(await words()).toEqual(['Nobody is here.', 'Step up to the desk.'])
    await sound('walk-up')
    await page.keyboard.press('o'); await page.getByTestId('skip-arrival').click(); await page.keyboard.press('Escape')

    await hold('empty', { chain })
    expect(await words()).toEqual(['Nobody is here.', 'Step up to the desk.'])
    await sound('nobody')

    // "Someone is here." at once; the line under it waits 1.5 s (a walk through must not flash "Standing still").
    await hold('still', { chain, alert: { state: 'counting', zone: 1, still_s: 9.3, limit_s: 10 } }, 'still')
    expect(await words()).toEqual(['Someone is here.', ''])
    await hold('still', { chain, alert: { state: 'counting', zone: 1, still_s: 9.3, limit_s: 10 } }, 'still')
    expect(await words()).toEqual(['Someone is here.', 'Standing still for 9 s'])
    await sound('still')
    await hold('still', { chain, alert: quiet }, 'moving')
    expect(await words()).toEqual(['Someone is here.', 'Moving'])

    await hold('still', { chain, alert: { state: 'check_on', zone: 1, still_s: 13.4, limit_s: 10 } }, 'still')
    expect(await words()).toEqual(['No movement for 13 s', "Step aside and back to say you're okay."])
    const fault = await page.evaluate(() => { const probe = document.createElement('i'); probe.style.color = 'var(--fault)'; document.body.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c })
    await expect(page.getByTestId('judge-headline')).toHaveCSS('color', fault)
    await sound('alert')

    const t = await page.evaluate(() => window.arrival.peek('still').t)
    await hold('still', { chain, alert: quiet, checkin: { t: t - 1000, link: 'pi5>pi5b:wifi' } }, 'moving')
    expect(await words()).toEqual(['Check-in received', 'Someone is here, moving'])
    await sound('check-in')

    await hold('empty', { chain, armed: true })
    expect(await words()).toEqual(['Armed.', 'This space should be empty.'])
    await sound('armed')
    await send('still', { chain, armed: true }); await page.evaluate(() => window.arrival.event('intrusion')); await hold('still', { chain, armed: true })
    expect(await words()).toEqual(['Someone is here.', 'This space should be empty.'])
    await expect(page.getByTestId('arrival-title')).toHaveCSS('color', fault)
    await sound('intrusion')
    await page.evaluate(() => window.arrival.event('disarmed'))

    await hold('blind', { chain })
    const blind = await words()
    expect(blind[0]).toBe('Sensor blind')
    expect(blind[1]).not.toBe('')
    await sound('blind')

    await send('empty', { chain }, null, true); await page.waitForTimeout(400)
    expect(await words()).toEqual(['No data', 'Waiting for the room signal.'])

    // The operator's drawer still opens over it, and Esc closes it.
    await hold('empty', { chain })
    await page.keyboard.press('o'); await expect(page.locator('.hud-operator')).toBeVisible()
    await expect(page.getByTestId('presenter')).toBeVisible()
    await page.keyboard.press('Escape'); await expect(page.locator('.hud-operator')).toBeHidden()
    expect(errors).toEqual([])
  })
}
