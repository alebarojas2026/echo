const { test, expect } = require('@playwright/test')
const path = require('node:path')
require('./layout-fixture.cjs')
const shots = process.env.HUD_SCREENSHOTS
const TEXT_2 = 'rgb(154, 163, 173)'
const TEXT = 'rgb(230, 232, 235)'

// #651: "0 cameras" and "Camera unplugged" are readings. A camera watcher that has gone quiet is "unknown".
test('the three camera wordings: unknown, unplugged and on', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.clock.install({ time: new Date('2026-01-01T00:00:00Z') })
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'))
  await page.goto('/tests/arrival-harness.html')
  await page.waitForLoadState('networkidle')
  await expect.poll(() => page.evaluate(() => !!window.arrival)).toBe(true)
  const send = async (scene, cam, ms) => { await page.evaluate(([scene, cam]) => window.arrival.update(scene, { cam }), [scene, cam]); await page.clock.runFor(ms) }
  const detail = page.getByTestId('arrival-detail')
  const line = page.getByTestId('cam-status')

  // Found while the board does not know about the camera: no claim about cameras at all.
  await send('still', 'unknown', 2000)
  await expect(page.getByTestId('arrival-title')).toHaveText('Found you.')
  await expect(detail).toHaveText('By radio.')
  if (shots) await page.screenshot({ path: path.join(shots, '1920-found-camera-unknown.png') })
  // Known to be unplugged: the reading.
  await send('still', 'off', 400)
  await expect(detail).toHaveText('0 cameras')
  await send('still', 'on', 400)
  await expect(detail).toHaveText('Camera teaching')

  // The main screen, after the greeting.
  await send('still', 'unknown', 4000)
  await expect(page.locator('.hud-arrival')).toBeHidden()
  await expect(line).toHaveText('Camera status unknown')
  await expect(line).toHaveCSS('color', TEXT_2)
  await expect(page.getByTestId('camera-unplug')).toBeHidden()
  if (shots) await page.screenshot({ path: path.join(shots, '1920-camera-unknown.png') })
  await send('still', 'off', 400)
  await expect(line).toHaveText('Camera unplugged · radio only')
  await expect(line).toHaveCSS('color', TEXT)
  // Unknown is not an unplugging: the unplug moment is only for a camera seen on and then read as off.
  await expect(page.getByTestId('camera-unplug')).toBeHidden()
  await send('still', 'on', 400)
  await send('still', 'unknown', 400)
  await expect(line).toHaveText('Camera status unknown')
  await expect(page.getByTestId('camera-unplug')).toBeHidden()
  await send('still', 'on', 400)
  await send('still', 'off', 400)
  await expect(page.getByTestId('camera-unplug')).toBeVisible()
})
