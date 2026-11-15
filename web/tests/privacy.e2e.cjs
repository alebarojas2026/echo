const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
for (const [width, height] of [[1920,1080],[1440,900]]) test(`privacy stays honest on both screens at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height })
  await page.clock.install()
  let value = { ok: true, images: 0, bytes_out: 0, since_t: 1000, t: 61000 }
  let broken = false, calls = 0
  await page.route('**/privacy', route => { calls++; return broken ? route.fulfill({ status: 404 }) : route.fulfill({ json: value }) })
  await page.goto('/tests/arrival-harness.html')
  const arrival = page.locator('.hud-arrival'), main = page.locator('#hud')
  await expect(arrival.getByTestId('privacy-values')).toHaveText('0 images stored · 0 bytes sent out')
  await expect(arrival.getByTestId('privacy-duration')).toHaveText('Counting for 1 min 0 s')
  await expect(arrival.getByTestId('privacy-values')).toHaveCSS('color', 'rgb(154, 163, 173)')
  const capture = async name => {
    if (!process.env.HUD_SCREENSHOTS) return
    fs.mkdirSync(process.env.HUD_SCREENSHOTS, { recursive: true })
    await page.screenshot({ path: path.join(process.env.HUD_SCREENSHOTS, `${width}-${name}.png`) })
  }
  await capture('arrival')
  value = { ...value, images: 2, bytes_out: 4096, t: 62000 }
  await page.clock.runFor(1100)
  await expect(arrival.getByTestId('privacy-values')).toHaveText('2 images stored · 4096 bytes sent out')
  await expect(arrival.getByTestId('privacy-values')).toHaveCSS('color', 'rgb(242, 85, 90)')
  await capture('fault')
  await page.evaluate(() => window.arrival.update('still'))
  await page.clock.runFor(6000)
  await expect(arrival).toBeHidden()
  await expect(main.getByTestId('privacy-values')).toBeVisible()
  await expect(main.getByTestId('privacy-values')).toHaveText('privacy meter not running')
  value = { ...value, images: 0, bytes_out: 0, t: 70000 }
  await page.clock.runFor(1100)
  await expect(main.getByTestId('privacy-values')).toHaveText('0 images stored · 0 bytes sent out')
  await capture('main')
  value = { ok: false, why: 'counter stopped' }
  await page.clock.runFor(1100)
  await expect(main.getByTestId('privacy-values')).toHaveText('privacy meter not running')
  await expect(main.getByTestId('privacy-duration')).toBeHidden()
  await capture('unavailable')
  broken = true
  await page.clock.runFor(1100)
  await expect(main.getByTestId('privacy-values')).toHaveText('privacy meter not running')
  expect(calls).toBeLessThan(15)
  await page.evaluate(() => window.arrival.dispose())
  const stopped = calls
  await page.clock.runFor(3000)
  expect(calls).toBe(stopped)
})
