const { test, expect } = require('@playwright/test')
const path = require('node:path')
const { layout } = require('./layout-fixture.cjs')
const shots = process.env.HUD_SCREENSHOTS
const capture = async (page, name) => {
  await expect(page.getByTestId('judge-headline')).toHaveCSS('opacity', '1')
  if (shots) await page.screenshot({ path: path.join(shots, name + '.png') })
}
const zone = layout.zones[0].id

// 40 saved seconds in the board's shape: empty, a visit, five seconds never saved, five where the sensor did not
// know, empty again.
function recorded(from) {
  const rows = []
  for (let i = 0; i < 40; i++) {
    if (i >= 20 && i < 25) continue
    const row = { t: from + i * 1000, present: false, zone: 0, zone_set: [], motion: null, armed: false, alert: false, health: 'ok', tamper: [] }
    if (i >= 10 && i < 20) Object.assign(row, { present: true, zone, zone_set: [zone], motion: 'moving' })
    if (i >= 25 && i < 30) Object.assign(row, { present: null, zone: null, health: 'blind' })
    rows.push(row)
  }
  return rows
}
async function open(page, history, width = 1920, height = 1080) {
  const calls = []
  await page.route('**/history?*', route => {
    const url = new URL(route.request().url())
    const from_t = Number(url.searchParams.get('from_t')), to_t = Number(url.searchParams.get('to_t'))
    calls.push({ from_t, to_t })
    const answer = history(from_t, to_t)
    return answer ? route.fulfill({ json: { from_t, to_t, step_s: 1, rows: answer } }) : route.fulfill({ status: 500, body: 'no' })
  })
  await page.setViewportSize({ width, height })
  await page.clock.install({ time: new Date('2026-01-01T14:14:00') })
  await page.clock.pauseAt(new Date('2026-01-01T14:14:01'))
  await page.goto('/tests/arrival-harness.html?records=board')
  await expect.poll(() => page.evaluate(() => !!window.arrival)).toBe(true)
  // Someone is standing there and has been greeted: the main screen is up and live.
  await page.evaluate(() => window.arrival.update('still'))
  await page.clock.runFor(6000)
  await expect(page.locator('.hud-arrival')).toBeHidden()
  return calls
}
const startLast = async page => {
  await page.keyboard.press('o')
  await page.getByTestId('replay-last').click()
  await expect(page.getByTestId('replay')).toBeVisible()
}

for (const [width, height] of [[1920, 1080], [1440, 900]]) {
  test(`a visit, a gap and an unknown stretch replay at 8x and hand back to live, at ${width}`, async ({ page }) => {
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const calls = await open(page, from => recorded(from), width, height)
    const headline = page.getByTestId('judge-headline')
    const banner = page.getByTestId('replay')
    const live = await headline.textContent()
    await startLast(page)
    expect(calls[0].to_t - calls[0].from_t).toBe(120000)
    await expect(page.locator('.hud-operator')).toBeHidden()
    await expect(banner.locator('.replay-line')).toHaveText(/^REPLAY\s*from the board’s records\s*\d+:\d\d (AM|PM)\s*8x$/)
    await expect(page.getByTestId('source-badge')).toHaveText('Replay')
    await expect(page.locator('#room')).toHaveAttribute('data-replay', 'on')
    for (const text of await banner.locator('strong, span, button').all()) expect(parseFloat(await text.evaluate(el => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(28)
    const box = await banner.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(640)
    expect(box.x + box.width).toBeLessThanOrEqual(width)
    await expect(banner.getByTestId('replay-live')).toBeInViewport({ ratio: 1 })

    await page.clock.runFor(1900) // second 15 of 40: the visit
    await expect(headline).toHaveText(/^Moving /)
    await expect(page.getByTestId('replay-word')).toHaveText('')
    await capture(page, `${width}-replay-visit`)
    await page.clock.runFor(900) // second 22: never saved
    await expect(page.getByTestId('replay-word')).toHaveText('No record')
    await expect(headline).toHaveText('No record')
    await expect(page.getByTestId('judge-detail')).toHaveText('Nothing was saved for this second.')
    await capture(page, `${width}-replay-no-record`)
    await page.clock.runFor(600) // second 27: saved, but the sensor did not know
    await expect(page.getByTestId('replay-word')).toHaveText('Sensor did not know')
    await expect(headline).toHaveText('Sensor did not know')
    await capture(page, `${width}-replay-did-not-know`)
    await page.clock.runFor(2500) // past the last second: back to live by itself
    await expect(banner).toBeHidden()
    await expect(page.getByTestId('source-badge')).toHaveText('Simulated')
    await expect(page.locator('#room')).toHaveAttribute('data-replay', '')
    await expect(headline).toHaveText(live)
    expect(errors).toEqual([])
  })
}

test('a live intrusion or tamper ends the replay at once', async ({ page }) => {
  await open(page, from => recorded(from))
  for (const kind of ['intrusion', 'tamper']) {
    await startLast(page)
    await page.clock.runFor(500)
    await expect(page.getByTestId('source-badge')).toHaveText('Replay')
    await page.evaluate(kind => window.arrival.event(kind), kind)
    await expect(page.getByTestId('replay')).toBeHidden()
    await expect(page.locator('#room')).toHaveAttribute('data-replay', '')
    await page.clock.runFor(300)
    await expect(page.getByTestId('source-badge')).toHaveText('Simulated')
  }
  // A device going silent while armed shows in the state too, with or without its event.
  await startLast(page)
  await page.clock.runFor(300)
  await page.evaluate(() => window.arrival.update('still', { armed: true, tamper: ['east'] }))
  await expect(page.getByTestId('replay')).toBeHidden()
})

test('an Ask answer with a span offers Replay; Esc, the button and the timeline work', async ({ page }) => {
  const calls = await open(page, from => recorded(from))
  await page.getByRole('button', { name: 'Ask the room', exact: true }).click()
  await page.getByRole('button', { name: 'Why did the Wi-Fi link drop?', exact: true }).click()
  await page.clock.runFor(700)
  await expect(page.getByTestId('ask-replay')).toBeHidden() // no span, no replay
  await page.getByLabel('Your question').fill('Was anyone here in the last 10 minutes?')
  await page.getByLabel('Your question').press('Enter')
  await page.clock.runFor(700)
  await expect(page.getByTestId('ask-answer')).toHaveText(/^Mock records: someone was here for \d+ s of the last 2 minutes\.$/)
  await page.getByTestId('ask-replay').click()
  await expect(page.locator('dialog')).not.toBeVisible()
  const banner = page.getByTestId('replay')
  await expect(banner).toBeVisible()
  expect(calls).toHaveLength(1)
  await page.clock.runFor(400)
  await page.keyboard.press('Escape')
  await expect(banner).toBeHidden()

  await startLast(page)
  const track = page.getByTestId('replay-track')
  const box = await track.boundingBox()
  await page.mouse.click(box.x + box.width * 0.9, box.y + box.height / 2)
  await expect(track).toHaveAttribute('aria-valuenow', '36')
  await expect(page.getByTestId('judge-headline')).not.toHaveText(/^Moving /)
  await track.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(track).toHaveAttribute('aria-valuenow', '31')
  await page.getByTestId('replay-live').click()
  await expect(banner).toBeHidden()
  await expect(page.locator('#room')).toHaveAttribute('data-replay', '')
})

test('records that cannot be read, or hold nothing, say so in words', async ({ page }) => {
  let rows = null
  await open(page, () => rows)
  await startLast(page)
  await expect(page.getByTestId('replay-word')).toHaveText('The records could not be read.')
  await expect(page.getByTestId('source-badge')).toHaveText('Simulated')
  await page.clock.runFor(4100)
  await expect(page.getByTestId('replay')).toBeHidden()
  rows = []
  await startLast(page)
  await expect(page.getByTestId('replay-word')).toHaveText('No record for this time.')
  await expect(page.locator('#room')).not.toHaveAttribute('data-replay', 'on')
})
