const layoutFixture = require('./layout-fixture.cjs')
const { test, expect } = require('@playwright/test')
const fs = require('node:fs')
const path = require('node:path')
const shots = process.env.HUD_SCREENSHOTS
for (const [scene, title, time] of [
  ['still', layoutFixture.still, 7200], ['alert', layoutFixture.still, 11000],
  ['object', 'An object, not a person', 1000], ['blind', 'Sensor blind', 1000],
  ['empty', 'Nobody is here', 1000],
]) {
  test(scene + ' judge screenshot', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.clock.install()
    await page.goto('/?mock=' + (scene === 'alert' ? 'still' : scene))
    await page.getByTestId('judge-headline').waitFor()
    await page.clock.runFor(time)
    await expect(page.getByTestId('judge-headline')).toHaveText(title)
    await page.evaluate(() => document.fonts.ready)
    const rail = page.locator('#hud')
    expect(await rail.evaluate(el => el.scrollHeight <= el.clientHeight)).toBe(true)
    expect(errors).toEqual([])
    if (shots) {
      fs.mkdirSync(shots, { recursive: true })
      await page.screenshot({ path: path.join(shots, scene + '.png') })
    }
  })
}
test('O toggles the operator view and ignores text entry', async ({ page }) => {
  await page.goto('/?mock=empty')
  const operator = page.getByRole('complementary', { name: 'Operator controls' })
  await expect(operator).toBeHidden()
  await page.keyboard.press('o')
  await expect(operator).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(operator).toBeHidden()
})
test('proof refreshes at thirty seconds', async ({ page }) => {
  let count = 0
  await page.route('**/proof.json', route => route.fulfill({ json: { bytes_out: ++count } }))
  await page.clock.install()
  await page.goto('/?mock=empty')
  await expect(page.getByTestId('bytes-out')).toHaveText('1')
  await page.clock.fastForward(30000)
  await expect(page.getByTestId('bytes-out')).toHaveText('2')
})
test('headline cases use the real mock state', async ({ page }) => {
  await page.goto('/?mock=still')
  const headlines = await page.evaluate(async () => {
    const { judgeMoment } = await import('/src/hud/judge-moment.ts')
    const { mockState } = await import('/src/hud/mock-layout.ts')
    return ['still', 'object', 'empty', 'blind'].map(name => judgeMoment(mockState(name, 0, 7000), false)[0])
  })
  expect(headlines).toEqual([layoutFixture.still, 'An object, not a person', 'Nobody is here', 'Sensor blind'])
})
