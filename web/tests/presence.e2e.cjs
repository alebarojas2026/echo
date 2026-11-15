const { test, expect } = require('@playwright/test')
const path = require('node:path')
const shots = process.env.HUD_SCREENSHOTS
const empty = { correct: null, total: null, always_empty_correct: null, cycles: null, method: 'held-out cycles, see PROOF.md' }

test('the Presence tile shows the measured counts with the always-empty score, and is not drawn until measured', async ({ page }) => {
  let proof = { presence: empty }
  await page.route('**/proof.json', route => route.fulfill({ json: proof }))
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.clock.install()
  await page.goto('/?mock=still')
  await page.clock.runFor(6000)
  const tile = page.getByTestId('presence-score')
  const baseline = page.getByTestId('presence-baseline')
  // Nothing measured: no tile, and with nothing else measured no proof block at all.
  await expect(tile).toBeHidden()
  await expect(baseline).toBeHidden()
  await expect(page.locator('#hud footer')).toBeHidden()

  // Presence is the only number measured: the block shows it alone.
  proof = { presence: { ...empty, correct: 1140, total: 1200, always_empty_correct: 600, cycles: 10 } }
  await page.clock.fastForward(30000)
  await expect(tile).toHaveText('1140 of 1200')
  await expect(baseline).toHaveText('always-empty would score 600 of 1200')
  await expect(page.getByTestId('zone-score')).toBeHidden()
  for (const part of [tile, baseline]) expect(parseFloat(await part.evaluate(el => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(28)
  const rail = page.locator('#hud')
  expect(await rail.evaluate(el => el.scrollHeight <= el.clientHeight && el.scrollWidth <= el.clientWidth)).toBe(true)
  if (shots) await page.screenshot({ path: path.join(shots, '1920-presence.png') })

  // No always-empty count: the score still shows, with nothing invented beside it.
  proof = { presence: { ...empty, correct: 19, total: 20 } }
  await page.clock.fastForward(30000)
  await expect(tile).toHaveText('19 of 20')
  await expect(baseline).toBeHidden()

  // With the other tiles it leads the block and nothing spills out of the rail.
  proof = { presence: { ...empty, correct: 19, total: 20, always_empty_correct: 10 }, zone: { correct: 1, total: 2 }, train_s: 2, bytes_out: 0, images_stored: 0 }
  await page.clock.fastForward(30000)
  await expect(page.getByTestId('zone-score')).toBeVisible()
  expect(await rail.evaluate(el => el.scrollHeight <= el.clientHeight)).toBe(true)
  if (shots) await page.screenshot({ path: path.join(shots, '1920-presence-with-others.png') })

  proof = { presence: null }
  await page.clock.fastForward(30000)
  await expect(tile).toBeHidden()
  await expect(page.locator('#hud footer')).toBeHidden()
})
