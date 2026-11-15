const { test, expect } = require('@playwright/test')
const fs = require('node:fs'), path = require('node:path')
const { layout } = require('./layout-fixture.cjs')
const from = 1763149300000
const report = count => ({ armed_from_t: from, armed_to_t: from + 120000, intrusions: count ? [{ t: from + 20000, zone: layout.zones[0].id }, { t: from + 60000, link: 'east>pi5:ble' }] : [], present_s: count ? 30 : 0, passed_by: null, tamper: [], blind_s: 0, text: count ? 'Two intrusion alerts were recorded. Someone was present for 30 seconds.' : 'No intrusion alerts were recorded during this armed stretch.', rows: 120, ms: 0 })
for (const [width, height] of [[1920,1080],[1440,900]]) test(`report on disarm, facts and each replay at ${width}`, async ({ page }) => {
  let count = 0, requests = 0
  const spans = []
  await page.setViewportSize({ width, height })
  await page.route('**/report', route => { requests++; return route.fulfill({ json: report(count) }) })
  await page.route('**/privacy', route => route.fulfill({ json: { ok: true, bytes_out: 0 } }))
  await page.route('**/history?*', route => {
    const url = new URL(route.request().url()), from_t = Number(url.searchParams.get('from_t')), to_t = Number(url.searchParams.get('to_t'))
    spans.push({ from_t, to_t }); return route.fulfill({ json: { from_t, to_t, step_s: 1, rows: [] } })
  })
  await page.goto('/tests/arrival-harness.html?records=board')
  await page.waitForFunction(() => window.arrival)
  const card = page.getByRole('dialog', { name: 'Incident report' })
  await expect(card).not.toBeVisible()
  await page.evaluate(() => { window.arrival.event('disarmed', 'quiet'); window.arrival.event('disarmed', 'quiet') })
  await expect(card).toBeVisible()
  await expect(page.getByTestId('report-text')).toContainText('No intrusion alerts')
  await expect(card.getByRole('button', { name: /Replay intrusion/ })).toHaveCount(0)
  await expect(page.getByTestId('report-time')).toHaveText('Report time: 0 ms')
  await expect(page.getByTestId('report-origin')).toHaveText('Written on the board · 0 bytes out')
  expect(requests).toBe(1)
  const capture = async scene => {
    if (!process.env.HUD_SCREENSHOTS) return
    fs.mkdirSync(process.env.HUD_SCREENSHOTS, { recursive: true })
    await page.screenshot({ path: path.join(process.env.HUD_SCREENSHOTS, `${width}-${scene}.png`) })
  }
  await capture('quiet')
  await card.getByRole('button', { name: 'Close', exact: true }).click()
  count = 2
  await page.evaluate(() => window.arrival.event('disarmed', 'two'))
  await expect(card.getByRole('button', { name: /Replay intrusion/ })).toHaveCount(2)
  await expect(page.getByTestId('report-facts')).toContainText('Passed by__')
  await capture('two')
  await card.getByRole('button', { name: 'Replay intrusion 1' }).click()
  await expect(card).not.toBeVisible()
  await expect.poll(() => spans.length).toBe(1)
  expect(spans[0]).toEqual({ from_t: from + 10000, to_t: from + 40000 })
  await page.evaluate(() => window.arrival.event('disarmed', 'again'))
  await card.getByRole('button', { name: 'Replay intrusion 2' }).click()
  await expect.poll(() => spans.length).toBe(2)
  expect(spans[1]).toEqual({ from_t: from + 50000, to_t: from + 80000 })
})
test('report errors retry and live alarms cancel a pending report', async ({ page }) => {
  let fail = true, release
  await page.route('**/report', async route => {
    if (fail) return route.fulfill({ status: 503 })
    if (release === null) await new Promise(resolve => { release = resolve })
    return route.fulfill({ json: { ...report(0), text: '<img src=x onerror=alert(1)>', ms: null } }).catch(() => {})
  })
  await page.route('**/privacy', route => route.fulfill({ status: 404 }))
  await page.goto('/tests/arrival-harness.html?records=board')
  await page.waitForFunction(() => window.arrival)
  await page.evaluate(() => window.arrival.event('disarmed'))
  await expect(page.getByTestId('report-status')).toHaveText('The report could not be read. Try again.')
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('report-text')).toHaveText('<img src=x onerror=alert(1)>')
  await expect(page.locator('.incident-report img')).toHaveCount(0)
  await expect(page.getByTestId('report-origin')).toHaveText('Written on the board · privacy meter not running')
  await expect(page.getByTestId('report-time')).toHaveText('Report time: __ ms')
  await page.keyboard.press('Escape')
  release = null
  await page.evaluate(() => window.arrival.event('disarmed'))
  await expect.poll(() => typeof release).toBe('function')
  await page.evaluate(() => window.arrival.event('intrusion'))
  release()
  await expect(page.locator('.incident-report')).not.toBeVisible()
})
