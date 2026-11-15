const { test, expect } = require('@playwright/test')
test('proof only shows measured tiles and hides an empty block', async ({ page }) => {
  let proof = {}
  await page.route('**/proof.json', route => route.fulfill({ json: proof }))
  await page.clock.install()
  await page.goto('/?mock=still')
  await page.clock.runFor(4000)
  const block = page.locator('#hud footer')
  await expect(block).toBeHidden()
  proof = { zone: { correct: 0, total: 2 }, train_s: 0, bytes_out: 0, images_stored: 0 }
  await page.clock.fastForward(30000)
  await expect(block).toBeVisible()
  for (const id of ['zone-score', 'train-seconds', 'bytes-out', 'images-stored']) await expect(page.getByTestId(id)).toBeVisible()
  for (const id of ['watts', 'models-count', 'ms-per-decision', 'person-object-score']) await expect(page.getByTestId(id)).toBeHidden()
  await expect(page.getByTestId('bytes-out')).toHaveText('0')
  proof = { zone: { correct: 1, total: 2 }, person_vs_object: { correct: 1, total: 2 }, train_s: 2, ms_per_decision: { p50: 3 }, watts: { radio_only: 4 }, bytes_out: 0, images_stored: 0, models_on_board: 1 }
  await page.clock.fastForward(30000)
  for (const id of ['zone-score', 'person-object-score', 'train-seconds', 'ms-per-decision', 'watts', 'bytes-out', 'images-stored', 'models-count']) await expect(page.getByTestId(id)).toBeVisible()
  proof = {}
  await page.clock.fastForward(30000)
  await expect(block).toBeHidden()
})
test('fresh arrival distinguishes training, recalibration and a moved router', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/tests/arrival-harness.html')
  await page.waitForFunction(() => window.arrival)
  await page.evaluate(() => window.arrival.update('empty', { pred: null, model: { trained: false } }))
  // With no decision and no model: a layout with sides waits for a lesson; one spot needs none and never asks for one.
  await expect(page.getByTestId('arrival-title')).toHaveText(/^(Not trained yet|Getting ready|One moment)$/)
  await page.evaluate(() => window.arrival.update('empty', { pred: null, model: { trained: true } }))
  await expect(page.getByTestId('arrival-title')).toHaveText('Recalibrating')
  await page.evaluate(() => window.arrival.update('empty', { pred: null, router: 'S-W30', armed: true }))
  await expect(page.getByTestId('arrival-title')).toHaveText('Paused')
  await expect(page.getByTestId('arrival-detail')).toHaveText('Armed. Monitoring is paused.')
  await page.evaluate(() => { window.arrival.update('still', { armed: true }); window.arrival.event('intrusion') })
  await expect(page.getByTestId('arrival-title')).toHaveText('Someone is here.')
})
