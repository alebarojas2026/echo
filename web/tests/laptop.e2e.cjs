// A 1366 x 768 laptop is a likely demo screen. The text column keeps its type sizes there:
// spacing gives way, never the 28 px floor for anything a judge reads.
const { test, expect } = require('@playwright/test')
const fs = require('node:fs')
const path = require('node:path')
const shots = process.env.HUD_SCREENSHOTS

for (const [scene, time] of [['still', 7200], ['object', 1000], ['blind', 1000], ['demo', 14000]]) {
  test(`${scene} at ${time} ms keeps full-size type on a 1366 x 768 laptop`, async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.clock.install()
    await page.goto('/?mock=' + scene)
    await page.getByTestId('judge-headline').waitFor({ state: 'attached' })
    await page.clock.runFor(time)
    await page.evaluate(() => document.fonts.ready)
    // On the one spot there is no column: the hall is the whole screen and the words sit on it.
    const hall = await page.evaluate(() => document.documentElement.dataset.judgeLayout === 'hall')
    const rail = await page.locator('#hud').evaluate(hud => {
      const shown = el => el.getClientRects().length > 0 && !el.closest('.hud-operator')
      const words = [...hud.querySelectorAll('*')].filter(el => shown(el) && [...el.childNodes].some(node => node.nodeType === 3 && node.textContent.trim()))
      const box = hud.getBoundingClientRect()
      return {
        transform: getComputedStyle(hud).transform,
        width: box.width,
        fits: hud.scrollHeight <= hud.clientHeight,
        smallest: Math.min(...words.map(el => parseFloat(getComputedStyle(el).fontSize))),
        headline: parseFloat(getComputedStyle(hud.querySelector('[data-testid="judge-headline"]')).fontSize),
        lowest: Math.max(...[...hud.children].filter(shown).map(el => el.getBoundingClientRect().bottom)),
      }
    })
    expect(rail.transform).toBe('none')
    expect(rail.width).toBe(hall ? 1366 : 640)
    expect(rail.fits).toBe(true)
    expect(rail.lowest).toBeLessThanOrEqual(768)
    expect(rail.smallest).toBeGreaterThanOrEqual(28)
    expect(rail.headline).toBeGreaterThanOrEqual(56)
    if (shots) {
      fs.mkdirSync(shots, { recursive: true })
      await page.screenshot({ path: path.join(shots, `1366-${scene}-${time}.png`) })
    }
  })
}
