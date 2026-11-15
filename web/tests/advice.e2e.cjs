const layoutFixture = require('./layout-fixture.cjs')
const { test, expect } = require('@playwright/test')
test('advice shows measured gains and preserves missing values', async ({ page }) => {
  await page.goto('/src/hud/index.html')
  await page.evaluate(async () => {
    const { mountPanel } = await import('/src/hud/judge-advice-panel.ts')
    const { mockState } = await import('/src/hud/mock-layout.ts')
    document.body.innerHTML = '<section id="panel"></section>'
    window.panel = mountPanel(document.querySelector('#panel'))
    window.state = mockState('object', 0, 1000)
    window.state.router = window.state.advice.to_spot
    window.panel.update(window.state, false)
  })
  await expect(page.getByTestId('advice-text')).toHaveText('Measuring…')
  await expect(page.getByTestId('after-dbm')).toHaveText('__')
  await page.evaluate(() => { Object.assign(window.state.advice, { before_dbm: -71.2, after_dbm: -63.4 }); window.panel.update(window.state, false) })
  await expect(page.getByTestId('advice-text')).toHaveText('+7.8 dB stronger')
  await page.evaluate(() => { window.state.advice.after_dbm = -73.3; window.panel.update(window.state, false) })
  await expect(page.getByTestId('advice-text')).toHaveText('−2.1 dB weaker')
  await page.evaluate(() => { window.state.advice = null; window.panel.update(window.state, false) })
  await expect(page.locator('#panel')).toBeHidden()
})
